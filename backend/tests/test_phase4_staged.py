"""Phase 4 staged generation: two-stage LLM chain behind CONTRACT_READER_LLM_STAGED."""

from __future__ import annotations

import io
import json
import os
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from app.llm import LLMRequest, LLMResult, LLMRouter
from app.main import create_app


def request(app: Any, method: str, path: str, payload: dict | None = None, *, headers: dict[str, str] | None = None, body: bytes | None = None, content_type: str | None = None) -> dict:
    if body is None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else b""
    result: dict[str, object] = {}

    def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
        result["status"] = int(status.split()[0])

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path.split("?", 1)[0],
        "QUERY_STRING": path.split("?", 1)[1] if "?" in path else "",
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": content_type or ("application/json" if payload is not None else ""),
        "wsgi.input": io.BytesIO(body),
    }
    for key, value in (headers or {}).items():
        environ["HTTP_" + key.upper().replace("-", "_")] = value
    result["body"] = json.loads(b"".join(app(environ, start_response)))
    return result


def multipart(text: str) -> tuple[bytes, str]:
    boundary = "staged-boundary"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="lease.txt"\r\n'
        "Content-Type: text/plain\r\n\r\n"
        f"{text}\r\n--{boundary}--\r\n"
    ).encode("utf-8")
    return body, f"multipart/form-data; boundary={boundary}"


class SequencedStaticProvider:
    """Static provider that answers by request kind, counting generation calls.

    Contract-type classification (upload and analysis) also uses the router;
    its schema requires ``contract_type`` and is answered with a harmless
    non-matching value so the deterministic classifier takes over.  Stage A is
    recognized by ``summary`` in the schema, Stage B by ``drafts``.
    """

    def __init__(self, stage_b_responses: list[dict[str, Any]]) -> None:
        self.stage_b_responses = list(stage_b_responses)
        self.stage_a_calls = 0
        self.stage_b_calls = 0
        self.name = "static"
        self.model = "fixture"

    def _answer(self, llm_request: LLMRequest) -> dict[str, Any]:
        required = set(llm_request.schema.get("required") or [])
        if "contract_type" in required:
            return {"contract_type": "not-a-rule-pack"}
        if "drafts" in required:
            response = self.stage_b_responses[min(self.stage_b_calls, len(self.stage_b_responses) - 1)]
            self.stage_b_calls += 1
            return response
        self.stage_a_calls += 1
        return STAGE_A_RESPONSE

    def generate(self, llm_request: LLMRequest) -> LLMResult:
        return LLMResult(
            content=json.dumps(self._answer(llm_request), ensure_ascii=False, separators=(",", ":")),
            provider=self.name,
            model=self.model,
            input_tokens=None,
            output_tokens=None,
            estimated_cost=0.0,
        )


STAGE_A_RESPONSE = {
    "summary": "合同明确约定押金应在退租后七日内退还。",
    "severity": "medium",
    "consequences": ["逾期结算可能产生履约争议。"],
    "actions": ["保存退租交接和结算凭证。"],
    "citations": [{"page": 1, "span_id": "p1-s1", "quote": "押金应在退租后七日内退还。"}],
}

STAGE_B_RESPONSE = {
    "actions": ["与对方书面确认押金退还期限。"],
    "drafts": {
        "message": "您好，关于押金退还，合同约定退租后七日内退还。我们能否一起确认交接安排和退还时间？",
        "supplement": "补充约定（待双方核对）\n一、押金在退租交接后七日内退还。\n甲方：________　乙方：________",
    },
}


class StagedGenerationTests(unittest.TestCase):
    db_seq = 0

    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.saved_staged = os.environ.get("CONTRACT_READER_LLM_STAGED")
        os.environ["CONTRACT_READER_LLM_STAGED"] = "on"

    def tearDown(self) -> None:
        if self.saved_staged is None:
            os.environ.pop("CONTRACT_READER_LLM_STAGED", None)
        else:
            os.environ["CONTRACT_READER_LLM_STAGED"] = self.saved_staged
        self.temp.cleanup()

    def prepare(self, provider: SequencedStaticProvider) -> tuple[Any, dict[str, str], str, Path]:
        # POST /v1/contracts classifies the contract type through the router
        # first, so the scripted sequence needs a leading (ignored) response.
        StagedGenerationTests.db_seq += 1
        db_path = Path(self.temp.name) / f"staged-{StagedGenerationTests.db_seq}.db"
        app = create_app(db_path, llm_router=LLMRouter([provider]))
        user = request(app, "POST", "/v1/users", {"display_name": "Carol", "email": "carol@example.test"})["body"]
        workspace = request(app, "POST", "/v1/workspaces", {"name": "Lease", "owner_id": user["user_id"]})["body"]
        headers = {"X-User-ID": user["user_id"], "X-Workspace-ID": workspace["workspace_id"]}
        body, content_type = multipart("押金应在退租后七日内退还。维修由甲方负责。")
        uploaded = request(app, "POST", "/v1/contracts", headers=headers, body=body, content_type=content_type)["body"]
        path = f"/v1/contracts/{uploaded['contract_id']}/versions/{uploaded['version_id']}/generate"
        return app, headers, path, db_path

    def test_staged_on_calls_provider_twice_and_merges_drafts(self) -> None:
        provider = SequencedStaticProvider([STAGE_B_RESPONSE])
        app, headers, path, db_path = self.prepare(provider)
        response = request(app, "POST", path, {"task": "解释押金条款"}, headers=headers)
        self.assertEqual(response["status"], 200, response)
        body = response["body"]
        self.assertEqual(body["generation_status"], "succeeded")
        self.assertEqual(provider.stage_a_calls, 1)
        self.assertEqual(provider.stage_b_calls, 1)
        self.assertEqual(body["llm"]["result"]["stages"], {"a": True, "b": True})
        self.assertEqual(body["llm"]["result"]["drafts"]["message"], STAGE_B_RESPONSE["drafts"]["message"])
        self.assertEqual(body["llm"]["result"]["drafts"]["supplement"], STAGE_B_RESPONSE["drafts"]["supplement"])
        self.assertEqual(body["llm"]["result"]["actions"], STAGE_B_RESPONSE["actions"])
        self.assertEqual(body["llm"]["provider"], "static")
        self.assertIsInstance(body["stage_b_latency_ms"], int)
        with closing(sqlite3.connect(db_path)) as connection:
            statuses = [row[0] for row in connection.execute("SELECT status FROM llm_invocations ORDER BY rowid").fetchall()]
        self.assertEqual(statuses, ["succeeded", "succeeded"])

    def test_staged_stage_b_failure_keeps_stage_a_result(self) -> None:
        invalid_stage_b = {"actions": ["缺少 drafts 键"], "drafts": {"message": "只有消息"}}
        provider = SequencedStaticProvider([invalid_stage_b])
        app, headers, path, db_path = self.prepare(provider)
        response = request(app, "POST", path, {"task": "解释押金条款"}, headers=headers)
        self.assertEqual(response["status"], 200, response)
        body = response["body"]
        self.assertEqual(provider.stage_a_calls, 1)
        self.assertEqual(provider.stage_b_calls, 1)
        self.assertEqual(body["generation_status"], "succeeded")
        self.assertNotIn("drafts", body["llm"]["result"])
        self.assertEqual(body["llm"]["result"]["stages"], {"a": True, "b": False})
        self.assertEqual(body["llm"]["result"]["citations"][0]["span_id"], "p1-s1")
        with closing(sqlite3.connect(db_path)) as connection:
            statuses = [row[0] for row in connection.execute("SELECT status FROM llm_invocations ORDER BY rowid").fetchall()]
        self.assertEqual(statuses, ["succeeded", "failed"])

    def test_staged_off_keeps_single_call_behavior(self) -> None:
        os.environ["CONTRACT_READER_LLM_STAGED"] = "off"
        provider = SequencedStaticProvider([STAGE_B_RESPONSE])
        app, headers, path, db_path = self.prepare(provider)
        response = request(app, "POST", path, {"task": "解释押金条款"}, headers=headers)
        self.assertEqual(response["status"], 200, response)
        body = response["body"]
        self.assertEqual(provider.stage_a_calls, 1)
        self.assertEqual(provider.stage_b_calls, 0)
        self.assertEqual(body["generation_status"], "succeeded")
        self.assertNotIn("drafts", body["llm"]["result"])
        self.assertNotIn("stages", body["llm"]["result"])
        self.assertNotIn("stage_b_latency_ms", body)
        self.assertEqual(body["llm"]["result"]["actions"], STAGE_A_RESPONSE["actions"])
        with closing(sqlite3.connect(db_path)) as connection:
            statuses = [row[0] for row in connection.execute("SELECT status FROM llm_invocations ORDER BY rowid").fetchall()]
        self.assertEqual(statuses, ["succeeded"])


if __name__ == "__main__":
    unittest.main()
