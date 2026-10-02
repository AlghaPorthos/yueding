from __future__ import annotations

import io
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any

from app.judge import JudgeError, JudgeResult
from app.llm import LLMRouter
from app.main import SCREEN_PRIORITIES, SCREEN_STANCES, create_app


LEASE_LINES = (
    "押金为一个月租金，退租后七日内返还。",
    "未经出租人书面同意，承租人不得改造房屋。",
    "房屋及附属设施的日常维修由出租人负责。",
    "承租人提前退租，应提前三十日通知并承担违约金。",
)
LEASE = "\n".join(LEASE_LINES)

ENTRY_KEYS = {
    "clause_type",
    "status",
    "stance",
    "interest_note",
    "priority",
    "confidence",
    "negotiation_hint",
    "evidence",
    "source",
}


def multipart(text: bytes, *, filename: str = "lease.txt", file_type: str = "text/plain") -> tuple[bytes, str]:
    boundary = "screen-boundary"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
        f"Content-Type: {file_type}\r\n\r\n"
    ).encode() + text + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def request(app, method: str, path: str, *, body: bytes = b"", content_type: str = "", headers: dict | None = None) -> dict:
    result: dict[str, Any] = {}
    request_headers = dict(headers or {})

    def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
        result["status"] = int(status.split()[0])

    path_only, _, query = path.partition("?")
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path_only,
        "QUERY_STRING": query,
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": content_type,
        "wsgi.input": io.BytesIO(body),
    }
    for key, value in request_headers.items():
        environ["HTTP_" + key.upper().replace("-", "_")] = value
    result["body"] = json.loads(b"".join(app(environ, start_response)))
    return result


class JudgeStub:
    def __init__(self, answers: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        self.answers = answers or {}
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def judge(self, state: str, questions: dict[str, Any]) -> JudgeResult:
        if self.error is not None:
            raise self.error
        self.calls.append({"state": state, "questions": questions})
        return JudgeResult(model="jev-test", answers=self.answers)


class RouterStub:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[Any] = []

    def describe(self) -> dict[str, Any]:
        return {"providers": [{"name": "stub", "model": "stub"}], "configured": True, "max_cost": 0.5}

    def generate(self, llm_request: Any, validator: Any = None) -> Any:
        self.calls.append(llm_request)
        if validator is not None:
            validator(self.content)
        return SimpleNamespace(
            content=self.content,
            provider="stub",
            model="stub",
            input_tokens=None,
            output_tokens=None,
            estimated_cost=0.0,
            latency_ms=1,
        )


def jev_answers() -> dict[str, Any]:
    return {
        "deposit.stance": {
            "type": "choice",
            "choice": "unfavorable",
            "probabilities": {"favorable": 0.05, "unfavorable": 0.9, "neutral": 0.03, "uncertain": 0.02},
        },
        "deposit.priority": {"type": "choice", "choice": "medium", "confidence": 0.8},
        "deposit.missing": {"type": "noul", "noul": 0.9},
        "modification.stance": {"type": "choice", "choice": "neutral"},
        "modification.priority": {"type": "choice", "choice": "low"},
        "modification.missing": {"type": "noul", "noul": 0.9},
        "repair.stance": {"type": "choice", "choice": "favorable"},
        "repair.priority": {"type": "choice", "choice": "low"},
        "repair.missing": {"type": "noul", "noul": 0.1},
        "early_termination.stance": {"type": "choice", "choice": "unfavorable"},
        "early_termination.priority": {"type": "choice", "choice": "high"},
        "early_termination.missing": {"type": "noul", "noul": 0.85},
    }


def llm_payload() -> list[dict[str, Any]]:
    return [
        {"clause_type": "deposit", "stance": "unfavorable", "priority": "high", "interest_note": "押金返还缺少逾期保障", "negotiation_hint": "补充返还期限与逾期利息", "confidence": 0.82},
        {"clause_type": "modification", "stance": "neutral", "priority": "low", "interest_note": "程序性限制", "negotiation_hint": "明确可实施范围", "confidence": 0.75},
        {"clause_type": "repair", "stance": "favorable", "priority": "low", "interest_note": "维修由对方承担", "negotiation_hint": "补充响应时限", "confidence": 0.75},
        {"clause_type": "early_termination", "stance": "unfavorable", "priority": "high", "interest_note": "违约金无上限", "negotiation_hint": "约定违约金上限", "confidence": 0.8},
    ]


class ScreenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.jev_keys = {key: os.environ.get(key) for key in ("CONTRACT_READER_JEV_API_KEY", "TYPESAFE_API_KEY")}
        os.environ.pop("CONTRACT_READER_JEV_API_KEY", None)
        os.environ.pop("TYPESAFE_API_KEY", None)
        self.app = create_app(Path(self.temp.name) / "app.db", llm_router=LLMRouter([]))

    def tearDown(self) -> None:
        self.temp.cleanup()
        for key, value in self.jev_keys.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def upload(self, content: str = LEASE, *, filename: str = "lease.txt", file_type: str = "text/plain", headers: dict | None = None) -> dict:
        body, content_type = multipart(content.encode("utf-8"), filename=filename, file_type=file_type)
        response = request(self.app, "POST", "/v1/contracts", body=body, content_type=content_type, headers=headers)
        self.assertEqual(response["status"], 200, response)
        return response["body"]

    def screen(self, uploaded: dict, *, payload: Any = None, headers: dict | None = None, version_id: str | None = None) -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else b""
        return request(
            self.app,
            "POST",
            f"/v1/contracts/{uploaded['contract_id']}/versions/{version_id or uploaded['version_id']}/screen",
            body=body,
            content_type="application/json" if payload is not None else "",
            headers=headers,
        )

    def test_deterministic_screen_maps_rental_clauses(self) -> None:
        uploaded = self.upload()
        response = self.screen(uploaded)

        self.assertEqual(response["status"], 200, response)
        payload = response["body"]
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["perspective"], "承租人")
        self.assertEqual(payload["engine"], "deterministic")
        self.assertEqual(
            payload["next"]["endpoint"],
            f"/v1/contracts/{uploaded['contract_id']}/versions/{uploaded['version_id']}/generate",
        )
        self.assertIn("generate", payload["next"]["hint"])
        self.assertTrue(payload["disclaimer"])

        findings = payload["findings"]
        self.assertEqual([item["clause_type"] for item in findings], ["deposit", "modification", "repair", "early_termination"])
        for finding, quote in zip(findings, LEASE_LINES):
            self.assertEqual(set(finding), ENTRY_KEYS, finding)
            self.assertEqual(finding["status"], "confirmed")
            self.assertEqual(finding["source"], "deterministic")
            self.assertEqual(finding["confidence"], 0.5)
            self.assertLessEqual(len(finding["interest_note"]), 60)
            self.assertLessEqual(len(finding["negotiation_hint"]), 60)
            self.assertTrue(finding["interest_note"])
            self.assertTrue(finding["negotiation_hint"])
            self.assertEqual(finding["evidence"], {"page": 1, "span_id": "p1-s1", "quote": quote})

        by_type = {item["clause_type"]: item for item in findings}
        self.assertEqual(by_type["deposit"]["stance"], "unfavorable")
        self.assertEqual(by_type["deposit"]["priority"], "medium")
        self.assertEqual(by_type["modification"]["stance"], "neutral")
        self.assertEqual(by_type["modification"]["priority"], "low")
        self.assertEqual(by_type["repair"]["stance"], "favorable")
        self.assertEqual(by_type["repair"]["priority"], "low")
        self.assertEqual(by_type["early_termination"]["stance"], "unfavorable")
        self.assertEqual(by_type["early_termination"]["priority"], "high")

    def test_screen_marks_missing_and_quality_blocked_clauses_uncertain(self) -> None:
        uploaded = self.upload("押金为一个月租金，退租后七日内返还。\n其余为一般租赁约定，内容足够长以通过质量检查。")
        response = self.screen(uploaded)
        self.assertEqual(response["status"], 200, response)
        findings = {item["clause_type"]: item for item in response["body"]["findings"]}
        self.assertEqual(response["body"]["engine"], "deterministic")
        self.assertEqual(findings["deposit"]["status"], "confirmed")
        for clause_type in ("modification", "repair", "early_termination"):
            entry = findings[clause_type]
            self.assertEqual(entry["status"], "not_found")
            self.assertEqual(entry["stance"], "uncertain")
            self.assertEqual(entry["priority"], "low")
            self.assertEqual(entry["source"], "deterministic")
            self.assertEqual(entry["interest_note"], "未找到相关约定")
            self.assertEqual(entry["evidence"], {})

        scanned = self.upload("押金为一个月租金", filename="scan.png", file_type="image/png")
        blocked = self.screen(scanned)
        self.assertEqual(blocked["status"], 200, blocked)
        self.assertEqual(blocked["body"]["engine"], "deterministic")
        for entry in blocked["body"]["findings"]:
            self.assertEqual(entry["status"], "needs_review")
            self.assertEqual(entry["stance"], "uncertain")
            self.assertEqual(entry["priority"], "low")
            self.assertEqual(entry["interest_note"], "文档质量不足，未生成确定性条款结果")
            self.assertEqual(entry["evidence"], {})

    def test_user_role_overrides_default_and_flips_stance(self) -> None:
        uploaded = self.upload()
        response = self.screen(uploaded, payload={"user_role": "出租人"})
        self.assertEqual(response["status"], 200, response)
        payload = response["body"]
        self.assertEqual(payload["perspective"], "出租人")
        by_type = {item["clause_type"]: item for item in payload["findings"]}
        self.assertEqual(by_type["deposit"]["stance"], "favorable")
        self.assertEqual(by_type["repair"]["stance"], "unfavorable")
        self.assertEqual(by_type["early_termination"]["stance"], "favorable")
        self.assertEqual(by_type["modification"]["stance"], "neutral")

    def test_default_perspective_follows_contract_type(self) -> None:
        privacy = self.upload(
            "本政策说明我们如何收集和处理个人信息。\n"
            "处理目的限于提供服务的必要范围，敏感个人信息需单独同意。\n"
            "个人信息保存期限为实现处理目的所必要的最短时间。"
        )
        response = self.screen(privacy)
        self.assertEqual(response["status"], 200, response)
        self.assertEqual(response["body"]["perspective"], "数据主体")
        self.assertEqual(
            [item["clause_type"] for item in response["body"]["findings"]],
            ["processing_scope", "consent_withdrawal", "sharing_delegation", "retention_period", "security_breach_notice"],
        )

        labor = self.upload(
            "劳动合同\n用人单位与劳动者约定试用期。\n劳动者工资按月支付，加班需审批。\n竞业限制期限两年。"
        )
        response = self.screen(labor, payload={"user_role": "用人单位"})
        self.assertEqual(response["status"], 200, response)
        self.assertEqual(response["body"]["perspective"], "用人单位")
        by_type = {item["clause_type"]: item for item in response["body"]["findings"]}
        self.assertEqual(by_type["probation_period"]["stance"], "uncertain")
        self.assertEqual(by_type["non_compete"]["stance"], "favorable")

    def test_invalid_user_role_is_rejected_like_align(self) -> None:
        uploaded = self.upload()
        response = self.screen(uploaded, payload={"user_role": "律师"})
        self.assertEqual(response["status"], 400, response)
        self.assertEqual(response["body"]["error"]["code"], "invalid_request")

        empty_json = self.screen(uploaded, payload={})
        non_json = request(
            self.app,
            "POST",
            f"/v1/contracts/{uploaded['contract_id']}/versions/{uploaded['version_id']}/screen",
            body="user_role=承租人".encode("utf-8"),
            content_type="text/plain",
        )
        for ok in (empty_json, non_json):
            self.assertEqual(ok["status"], 200, ok)
            self.assertEqual(ok["body"]["perspective"], "承租人")

    def test_screen_returns_404_for_unknown_contract_or_version(self) -> None:
        uploaded = self.upload()
        response = self.screen(uploaded, version_id="00000000-0000-0000-0000-000000000000")
        self.assertEqual(response["status"], 404, response)
        self.assertEqual(response["body"]["error"]["code"], "not_found")

        missing = request(self.app, "POST", f"/v1/contracts/no-such-contract/versions/{uploaded['version_id']}/screen")
        self.assertEqual(missing["status"], 404, missing)

    def test_jev_engine_maps_answers_to_fields(self) -> None:
        uploaded = self.upload()
        stub = JudgeStub(answers=jev_answers())
        self.app._judge_provider = lambda: stub
        response = self.screen(uploaded)

        self.assertEqual(response["status"], 200, response)
        payload = response["body"]
        self.assertEqual(payload["engine"], "jev")
        self.assertEqual(payload["perspective"], "承租人")

        self.assertEqual(len(stub.calls), 1)
        state = stub.calls[0]["state"]
        questions = stub.calls[0]["questions"]
        self.assertEqual(len(questions), 12)
        self.assertIn("我方立场：承租人", state)
        for quote in LEASE_LINES:
            self.assertIn(quote, state)
        self.assertEqual(questions["deposit.stance"]["type"], "choice")
        self.assertEqual(set(questions["deposit.stance"]["criteria"]), set(SCREEN_STANCES))
        self.assertEqual(questions["deposit.priority"]["type"], "choice")
        self.assertEqual(set(questions["deposit.priority"]["criteria"]), set(SCREEN_PRIORITIES))
        self.assertEqual(questions["deposit.missing"]["type"], "noul")
        self.assertTrue(questions["deposit.missing"]["instructions"])

        by_type = {item["clause_type"]: item for item in payload["findings"]}
        for entry in by_type.values():
            self.assertEqual(entry["source"], "jev")
        self.assertEqual(by_type["deposit"]["stance"], "unfavorable")
        self.assertEqual(by_type["deposit"]["priority"], "medium")
        self.assertEqual(by_type["deposit"]["interest_note"], "押金返还约定缺少逾期责任，返还保障不足")
        self.assertEqual(by_type["deposit"]["confidence"], 0.9)
        self.assertEqual(by_type["modification"]["stance"], "neutral")
        self.assertTrue(by_type["modification"]["interest_note"].endswith("；缺少保护性约定"))
        self.assertLessEqual(len(by_type["modification"]["interest_note"]), 60)
        self.assertEqual(by_type["modification"]["confidence"], 0.7)
        self.assertEqual(by_type["repair"]["stance"], "favorable")
        self.assertEqual(by_type["early_termination"]["stance"], "unfavorable")
        self.assertEqual(by_type["early_termination"]["priority"], "high")

    def test_jev_invalid_answer_for_one_clause_falls_back_per_clause(self) -> None:
        uploaded = self.upload()
        answers = jev_answers()
        answers["early_termination.stance"] = {"type": "choice", "choice": "maybe"}
        stub = JudgeStub(answers=answers)
        self.app._judge_provider = lambda: stub
        response = self.screen(uploaded)

        self.assertEqual(response["status"], 200, response)
        payload = response["body"]
        self.assertEqual(payload["engine"], "jev")
        by_type = {item["clause_type"]: item for item in payload["findings"]}
        self.assertEqual(by_type["deposit"]["source"], "jev")
        self.assertEqual(by_type["early_termination"]["source"], "deterministic")
        self.assertEqual(by_type["early_termination"]["stance"], "unfavorable")
        self.assertEqual(by_type["early_termination"]["priority"], "high")

    def test_jev_error_falls_back_to_deterministic(self) -> None:
        uploaded = self.upload()
        stub = JudgeStub(error=JudgeError("provider_unreachable"))
        self.app._judge_provider = lambda: stub
        response = self.screen(uploaded)

        self.assertEqual(response["status"], 200, response)
        payload = response["body"]
        self.assertEqual(payload["engine"], "deterministic")
        by_type = {item["clause_type"]: item for item in payload["findings"]}
        self.assertEqual(by_type["deposit"]["stance"], "unfavorable")
        self.assertEqual(by_type["deposit"]["confidence"], 0.5)
        for entry in by_type.values():
            self.assertEqual(entry["source"], "deterministic")

    def test_llm_engine_maps_strict_json(self) -> None:
        uploaded = self.upload()
        router = RouterStub(json.dumps({"findings": llm_payload()}, ensure_ascii=False))
        self.app.llm_router = router
        response = self.screen(uploaded)

        self.assertEqual(response["status"], 200, response)
        payload = response["body"]
        self.assertEqual(payload["engine"], "llm")
        self.assertEqual(len(router.calls), 1)
        by_type = {item["clause_type"]: item for item in payload["findings"]}
        for entry in by_type.values():
            self.assertEqual(entry["source"], "llm")
        self.assertEqual(by_type["deposit"]["stance"], "unfavorable")
        self.assertEqual(by_type["deposit"]["priority"], "high")
        self.assertEqual(by_type["deposit"]["interest_note"], "押金返还缺少逾期保障")
        self.assertEqual(by_type["deposit"]["negotiation_hint"], "补充返还期限与逾期利息")
        self.assertEqual(by_type["deposit"]["confidence"], 0.82)

    def test_llm_invalid_payload_falls_back_to_deterministic(self) -> None:
        uploaded = self.upload()

        self.app.llm_router = RouterStub("not-json{")
        broken = self.screen(uploaded)
        self.assertEqual(broken["status"], 200, broken)
        self.assertEqual(broken["body"]["engine"], "deterministic")

        bad_enum = llm_payload()
        bad_enum[0]["stance"] = "angry"
        self.app.llm_router = RouterStub(json.dumps({"findings": bad_enum}, ensure_ascii=False))
        invalid = self.screen(uploaded)
        self.assertEqual(invalid["status"], 200, invalid)
        self.assertEqual(invalid["body"]["engine"], "deterministic")
        by_type = {item["clause_type"]: item for item in invalid["body"]["findings"]}
        self.assertEqual(by_type["deposit"]["source"], "deterministic")
        self.assertEqual(by_type["deposit"]["stance"], "unfavorable")

        missing_clause = llm_payload()[:2]
        self.app.llm_router = RouterStub(json.dumps({"findings": missing_clause}, ensure_ascii=False))
        partial = self.screen(uploaded)
        self.assertEqual(partial["status"], 200, partial)
        self.assertEqual(partial["body"]["engine"], "deterministic")

    def test_screen_writes_audit_row(self) -> None:
        user = request(
            self.app,
            "POST",
            "/v1/users",
            body=json.dumps({"display_name": "Alice", "email": "alice@example.test"}, ensure_ascii=False).encode("utf-8"),
            content_type="application/json",
        )
        self.assertEqual(user["status"], 201, user)
        workspace = request(
            self.app,
            "POST",
            "/v1/workspaces",
            body=json.dumps({"name": "Lease review", "owner_id": user["body"]["user_id"]}, ensure_ascii=False).encode("utf-8"),
            content_type="application/json",
        )
        self.assertEqual(workspace["status"], 201, workspace)
        headers = {"X-User-ID": user["body"]["user_id"], "X-Workspace-ID": workspace["body"]["workspace_id"]}

        uploaded = self.upload(headers=headers)
        response = self.screen(uploaded, headers=headers)
        self.assertEqual(response["status"], 200, response)

        events = request(self.app, "GET", "/v1/audit-events", headers=headers)
        self.assertEqual(events["status"], 200, events)
        screen_events = [event for event in events["body"]["events"] if event["action"] == "contract.screen"]
        self.assertEqual(len(screen_events), 1)
        event = screen_events[0]
        self.assertEqual(event["resource_id"], uploaded["version_id"])
        self.assertEqual(event["metadata"]["contract_id"], uploaded["contract_id"])
        self.assertEqual(event["metadata"]["engine"], "deterministic")
        self.assertEqual(event["metadata"]["perspective"], "承租人")


if __name__ == "__main__":
    unittest.main()
