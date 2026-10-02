from __future__ import annotations

import io
import json
import os
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from app.llm import LLMRouter, StaticProvider
from app.main import create_app


def request(app, method: str, path: str, payload: dict | None = None, *, headers: dict[str, str] | None = None, body: bytes | None = None, content_type: str | None = None) -> dict:
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
    boundary = "llm-boundary"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="lease.txt"\r\n'
        "Content-Type: text/plain\r\n\r\n"
        f"{text}\r\n--{boundary}--\r\n"
    ).encode("utf-8")
    return body, f"multipart/form-data; boundary={boundary}"


class LLMApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        response = {
            "summary": "合同明确约定押金退还期限。",
            "severity": "medium",
            "consequences": ["逾期结算可能产生履约争议。"],
            "actions": ["保存退租交接和结算凭证。"],
            "citations": [{"page": 1, "span_id": "p1-s1", "quote": "押金应在退租后七日内退还。"}],
        }
        self.app = create_app(
            Path(self.temp.name) / "app.db",
            llm_router=LLMRouter([StaticProvider(response)]),
        )
        user = request(self.app, "POST", "/v1/users", {"display_name": "Alice", "email": "alice@example.test"})["body"]
        workspace = request(self.app, "POST", "/v1/workspaces", {"name": "Lease", "owner_id": user["user_id"]})["body"]
        self.headers = {"X-User-ID": user["user_id"], "X-Workspace-ID": workspace["workspace_id"]}
        body, content_type = multipart("押金应在退租后七日内退还。维修由甲方负责。")
        uploaded = request(self.app, "POST", "/v1/contracts", headers=self.headers, body=body, content_type=content_type)
        self.contract = uploaded["body"]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_generate_is_evidence_constrained_and_recorded(self) -> None:
        path = f"/v1/contracts/{self.contract['contract_id']}/versions/{self.contract['version_id']}/generate"
        response = request(self.app, "POST", path, {"task": "解释押金条款"}, headers=self.headers)
        self.assertEqual(response["status"], 200, response)
        body = response["body"]
        self.assertEqual(body["generation_status"], "succeeded")
        self.assertEqual(body["llm"]["result"]["citations"][0]["span_id"], "p1-s1")
        with closing(sqlite3.connect(Path(self.temp.name) / "app.db")) as connection:
            status, provider = connection.execute("SELECT status, provider FROM llm_invocations").fetchone()
        self.assertEqual((status, provider), ("succeeded", "static"))

    def test_invalid_provider_output_keeps_deterministic_result(self) -> None:
        invalid = {
            "summary": "越界引用",
            "severity": "high",
            "consequences": [],
            "actions": [],
            "citations": [{"page": 9, "span_id": "p9-s1", "quote": "不存在"}],
        }
        app = create_app(Path(self.temp.name) / "invalid.db", llm_router=LLMRouter([StaticProvider(invalid)]))
        user = request(app, "POST", "/v1/users", {"display_name": "Bob", "email": "bob@example.test"})["body"]
        workspace = request(app, "POST", "/v1/workspaces", {"name": "Lease", "owner_id": user["user_id"]})["body"]
        headers = {"X-User-ID": user["user_id"], "X-Workspace-ID": workspace["workspace_id"]}
        body, content_type = multipart("押金应在退租后七日内退还。")
        uploaded = request(app, "POST", "/v1/contracts", headers=headers, body=body, content_type=content_type)["body"]
        path = f"/v1/contracts/{uploaded['contract_id']}/versions/{uploaded['version_id']}/generate"
        result = request(app, "POST", path, headers=headers)
        # 越界引用被剔除而不是整体拒绝：摘要与合法引用仍然可用
        self.assertEqual(result["body"]["generation_status"], "succeeded")
        self.assertEqual(result["body"]["llm"]["result"]["citations"], [])
        self.assertTrue(result["body"]["deterministic"]["findings"])

    def test_unconfigured_provider_is_explicit_and_readiness_exposes_configuration(self) -> None:
        saved = {key: os.environ.pop(key, None) for key in (
            "ZAI_API_KEY", "ZAI_API_URL", "ZAI_BASE_URL", "ZAI_MODEL", "GLM_MODEL",
            "CONTRACT_READER_LLM_PRIMARY_URL", "CONTRACT_READER_LLM_PRIMARY_MODEL",
            "CONTRACT_READER_LLM_PRIMARY_API_KEY",
        )}
        try:
            app = create_app(Path(self.temp.name) / "empty.db")
        finally:
            for key, value in saved.items():
                if value is not None:
                    os.environ[key] = value
        ready = request(app, "GET", "/readyz")
        self.assertEqual(ready["status"], 200)
        self.assertFalse(ready["body"]["llm"]["configured"])
        body, content_type = multipart("押金应在退租后七日内退还。")
        uploaded = request(app, "POST", "/v1/contracts", body=body, content_type=content_type)["body"]
        result = request(app, "POST", f"/v1/contracts/{uploaded['contract_id']}/versions/{uploaded['version_id']}/generate")
        self.assertEqual(result["body"]["generation_status"], "failed")
        self.assertEqual(result["body"]["error"]["code"], "not_configured")
        metrics = request(app, "GET", "/metrics")
        self.assertEqual(metrics["body"]["llm_invocations"]["failed"], 1)

    def test_zai_key_uses_v4_chat_completions_defaults(self) -> None:
        saved = {key: os.environ.get(key) for key in (
            "ZAI_API_KEY", "ZAI_API_URL", "ZAI_BASE_URL", "ZAI_MODEL",
            "CONTRACT_READER_LLM_PRIMARY_URL", "CONTRACT_READER_LLM_PRIMARY_MODEL",
            "CONTRACT_READER_LLM_PRIMARY_API_KEY",
        )}
        try:
            for key in saved:
                os.environ.pop(key, None)
            os.environ["ZAI_API_KEY"] = "test-key"
            described = LLMRouter.from_env().describe()
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        self.assertEqual(described["providers"], [{"name": "primary", "model": "glm-5.3-flash"}])
        self.assertTrue(described["configured"])


if __name__ == "__main__":
    unittest.main()
