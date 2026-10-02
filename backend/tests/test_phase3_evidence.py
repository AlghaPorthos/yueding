"""Phase 3 证据契约：analyze/align findings 的确定性 severity/consequences/provenance。

- ``POST /contracts/{cid}/versions/{vid}/analyze`` 的每条 finding 都带
  ``severity``（low/medium/high/unknown 枚举）、``consequences``（字符串数组，
  取自 action_card.impact/message，至多 2 条）和 ``provenance="deterministic"``。
- severity 启发式复用 /screen 确定性引擎的关键词立场表（弱方默认视角）：
  screen 判 unfavorable+high 的条款 → high；unfavorable → medium；其余
  confirmed → low；非 confirmed → unknown。
- /align 的 findings（alignments）逐条透传同一组字段。
"""

from __future__ import annotations

import io
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from app.main import create_app

DEPOSIT_LINE = "押金为一个月租金，退租后七日内返还。"
MODIFICATION_LINE = "未经出租人书面同意，承租人不得改造房屋。"
# 命中 deposit 立场表第一条（"不予退还"）：unfavorable + high。
DEPOSIT_FORFEIT_LINE = "押金为一个月租金，退租时一律不予退还。"

SEVERITIES = {"low", "medium", "high", "unknown"}

# 与 test_matters_projection 一致：隔离真实 Jev 凭证，保证 screen 走确定性引擎。
JUDGE_ENV_KEYS = ("CONTRACT_READER_JEV_API_KEY", "TYPESAFE_API_KEY")


def multipart(text: bytes, *, filename: str = "lease.txt", file_type: str = "text/plain") -> tuple[bytes, str]:
    boundary = "phase3-boundary"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="{filename}"\r\nContent-Type: {file_type}\r\n\r\n'
    ).encode() + text + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def request(app: Any, method: str, path: str, *, body: bytes = b"", content_type: str = "") -> dict:
    result: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        result["status"] = int(status.split()[0])

    path_only, _, query = path.partition("?")
    output = b"".join(app({
        "REQUEST_METHOD": method,
        "PATH_INFO": path_only,
        "QUERY_STRING": query,
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": content_type,
        "wsgi.input": io.BytesIO(body),
    }, start_response))
    result["body"] = json.loads(output)
    return result


class Phase3EvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.app = create_app(Path(self.temp.name) / "app.db")
        self._saved_judge_env = {key: os.environ.pop(key, None) for key in JUDGE_ENV_KEYS}

    def tearDown(self) -> None:
        for key, value in self._saved_judge_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temp.cleanup()

    def upload(self, content: str, *, filename: str = "lease.txt") -> dict:
        body, content_type = multipart(content.encode("utf-8"), filename=filename)
        response = request(self.app, "POST", "/contracts", body=body, content_type=content_type)
        self.assertEqual(response["status"], 201, response)
        return response["body"]

    def analyze(self, uploaded: dict) -> list[dict[str, Any]]:
        response = request(
            self.app,
            "POST",
            f"/contracts/{uploaded['contract_id']}/versions/{uploaded['version_id']}/analyze",
        )
        self.assertEqual(response["status"], 200, response)
        return response["body"]["findings"]

    def screen(self, uploaded: dict) -> dict[str, Any]:
        response = request(
            self.app,
            "POST",
            f"/v1/contracts/{uploaded['contract_id']}/versions/{uploaded['version_id']}/screen",
        )
        self.assertEqual(response["status"], 200, response)
        return response["body"]

    def test_every_analyze_finding_carries_severity_and_deterministic_provenance(self) -> None:
        uploaded = self.upload("\n".join((DEPOSIT_LINE, MODIFICATION_LINE)))

        findings = self.analyze(uploaded)

        self.assertTrue(findings)
        for finding in findings:
            with self.subTest(finding=finding["type"]):
                self.assertIn(finding["severity"], SEVERITIES, finding)
                self.assertEqual(finding["provenance"], "deterministic", finding)
                self.assertIsInstance(finding["consequences"], list, finding)
                confirmed = finding["status"] == "confirmed"
                for evidence in finding["contract_evidence"]:
                    self.assertTrue(str(evidence.get("quote", "")).strip(), finding)

    def test_screen_unfavorable_high_priority_clause_maps_to_high_severity(self) -> None:
        uploaded = self.upload(DEPOSIT_FORFEIT_LINE)

        screened = self.screen(uploaded)
        deposit_screen = next(
            item for item in screened["findings"] if item["clause_type"] == "deposit"
        )
        self.assertEqual(deposit_screen["stance"], "unfavorable", deposit_screen)
        self.assertEqual(deposit_screen["priority"], "high", deposit_screen)

        deposit = next(finding for finding in self.analyze(uploaded) if finding["type"] == "deposit")
        self.assertEqual(deposit["status"], "confirmed", deposit)
        self.assertEqual(deposit["severity"], "high", deposit)

    def test_confirmed_consequences_are_non_empty_strings(self) -> None:
        uploaded = self.upload("\n".join((DEPOSIT_LINE, MODIFICATION_LINE)))

        for finding in self.analyze(uploaded):
            with self.subTest(finding=finding["type"]):
                for consequence in finding["consequences"]:
                    self.assertIsInstance(consequence, str, finding)
                    self.assertTrue(consequence.strip(), finding)
                if finding["status"] == "confirmed":
                    self.assertTrue(finding["consequences"], finding)

    def test_missing_clauses_stay_unknown_with_empty_consequences(self) -> None:
        uploaded = self.upload("本合同仅约定租金和租期。\n")

        findings = self.analyze(uploaded)

        self.assertTrue(all(finding["status"] == "not_found" for finding in findings))
        for finding in findings:
            self.assertEqual(finding["severity"], "unknown", finding)
            self.assertEqual(finding["consequences"], [], finding)
            self.assertEqual(finding["provenance"], "deterministic", finding)

    def test_align_findings_pass_through_severity_consequences_provenance(self) -> None:
        uploaded = self.upload("\n".join((DEPOSIT_LINE, MODIFICATION_LINE)))

        response = request(
            self.app,
            "POST",
            f"/contracts/{uploaded['contract_id']}/versions/{uploaded['version_id']}/align",
        )
        self.assertEqual(response["status"], 200, response)

        for item in response["body"]["findings"]:
            with self.subTest(finding=item["type"]):
                self.assertIn(item["severity"], SEVERITIES, item)
                self.assertEqual(item["provenance"], "deterministic", item)
                self.assertIsInstance(item["consequences"], list, item)

        deposit = next(item for item in response["body"]["findings"] if item["type"] == "deposit")
        self.assertEqual(deposit["severity"], "medium", deposit)


if __name__ == "__main__":
    unittest.main()
