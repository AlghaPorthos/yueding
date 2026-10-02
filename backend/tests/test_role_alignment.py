from __future__ import annotations

import io
import json
import os
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from app.main import create_app

# Two corpus provisions that both match the early_termination query with the
# same term score; the no-role order therefore falls through to the stable
# source tie-break (住房租赁条例 sorts before 商品房屋租赁管理办法).
TENANT_QUOTE = "乙方提前退租的，承租人可以解除合同并提前三十日通知出租人，违约金不得超过一个月租金。"
LESSOR_QUOTE = "承租人拖欠租金的，出租人有权解除合同并收回房屋；提前退租的应支付违约金。"

CONTRACT = "\n".join((
    "押金为一个月租金，退租后七日内返还。",
    "未经出租人书面同意，承租人不得改造房屋。",
    "房屋及附属设施的日常维修由出租人负责。",
    "乙方提前退租的，应提前三十日书面通知出租人并支付违约金。",
))


def multipart(text: bytes, *, filename: str = "lease.txt", file_type: str = "text/plain") -> tuple[bytes, str]:
    boundary = "role-boundary"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="{filename}"\r\nContent-Type: {file_type}\r\n\r\n'
    ).encode() + text + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def request(app, method: str, path: str, *, body: bytes = b"", content_type: str = "") -> dict:
    result: dict[str, object] = {}

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


class RoleAlignmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        # 隔离真实 Jev 凭证：align 判定路径复活后，live key 会把结果变成网络依赖。
        self._old_jev = {k: os.environ.pop(k, None) for k in ("CONTRACT_READER_JEV_API_KEY", "TYPESAFE_API_KEY")}
        self.app = create_app(Path(self.temp.name) / "app.db")
        corpus = Path(self.temp.name) / "legal.jsonl"
        corpus.write_text("".join(
            json.dumps(record, ensure_ascii=False) + "\n"
            for record in (
                {"source": "商品房屋租赁管理办法", "article": "第五条", "version": "2026-01-01", "quote": TENANT_QUOTE},
                {"source": "住房租赁条例", "article": "第八条", "version": "2026-01-01", "quote": LESSOR_QUOTE},
            )
        ), encoding="utf-8")
        self._old_corpus = os.environ.get("CONTRACT_READER_LEGAL_CORPUS")
        os.environ["CONTRACT_READER_LEGAL_CORPUS"] = str(corpus)

    def tearDown(self) -> None:
        for key, value in self._old_jev.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if self._old_corpus is None:
            os.environ.pop("CONTRACT_READER_LEGAL_CORPUS", None)
        else:
            os.environ["CONTRACT_READER_LEGAL_CORPUS"] = self._old_corpus
        self.temp.cleanup()

    def upload(self) -> dict:
        body, content_type = multipart(CONTRACT.encode("utf-8"))
        response = request(self.app, "POST", "/v1/contracts", body=body, content_type=content_type)
        self.assertEqual(response["status"], 200, response)
        return response["body"]

    def align(self, uploaded: dict, *, body: bytes = b"", content_type: str = "") -> dict:
        return request(
            self.app,
            "POST",
            f"/v1/contracts/{uploaded['contract_id']}/versions/{uploaded['version_id']}/align",
            body=body,
            content_type=content_type,
        )

    @staticmethod
    def quotes(payload: dict) -> list[str]:
        findings = {item["type"]: item for item in payload["findings"]}
        return [item["quote"] for item in findings["early_termination"]["legal_provisions"]]

    def test_tenant_role_ranks_tenant_perspective_first(self) -> None:
        uploaded = self.upload()
        response = self.align(
            uploaded,
            body=json.dumps({"user_role": "承租人"}, ensure_ascii=False).encode("utf-8"),
            content_type="application/json",
        )

        self.assertEqual(response["status"], 200, response)
        findings = {item["type"]: item for item in response["body"]["findings"]}
        termination = findings["early_termination"]
        self.assertEqual(termination["alignment_status"], "matched")
        self.assertEqual(self.quotes(response["body"]), [TENANT_QUOTE, LESSOR_QUOTE])
        self.assertEqual(termination["reasoning"]["user_role"], "承租人")

        with closing(sqlite3.connect(Path(self.temp.name) / "app.db")) as connection:
            row = connection.execute(
                "SELECT legal_provisions, reasoning FROM legal_alignments "
                "WHERE version_id = ? AND clause_type = 'early_termination'",
                (uploaded["version_id"],),
            ).fetchone()
        self.assertIsNotNone(row)
        persisted_provisions = json.loads(row[0])
        persisted_reasoning = json.loads(row[1])
        self.assertEqual([item["quote"] for item in persisted_provisions], [TENANT_QUOTE, LESSOR_QUOTE])
        self.assertEqual(persisted_reasoning["user_role"], "承租人")

    def test_lessor_role_ranks_lessor_perspective_first(self) -> None:
        uploaded = self.upload()
        response = self.align(
            uploaded,
            body=json.dumps({"user_role": "出租人"}, ensure_ascii=False).encode("utf-8"),
            content_type="application/json",
        )

        self.assertEqual(response["status"], 200, response)
        self.assertEqual(self.quotes(response["body"]), [LESSOR_QUOTE, TENANT_QUOTE])
        findings = {item["type"]: item for item in response["body"]["findings"]}
        self.assertEqual(findings["early_termination"]["reasoning"]["user_role"], "出租人")

    def test_role_rerank_keeps_provenance_fields_stable(self) -> None:
        uploaded = self.upload()
        baseline = self.align(uploaded)
        self.assertEqual(baseline["status"], 200, baseline)
        baseline_provisions = {
            finding["type"]: finding for finding in baseline["body"]["findings"]
        }["early_termination"]["legal_provisions"]
        baseline_hashes = {item["quote"]: item["content_hash"] for item in baseline_provisions}

        for role in ("承租人", "出租人"):
            response = self.align(
                uploaded,
                body=json.dumps({"user_role": role}, ensure_ascii=False).encode("utf-8"),
                content_type="application/json",
            )
            self.assertEqual(response["status"], 200, response)
            provisions = {
                finding["type"]: finding for finding in response["body"]["findings"]
            }["early_termination"]["legal_provisions"]
            # Ordering may flip with the role; each provision's provenance
            # fields must stay byte-identical to the no-role baseline.
            self.assertEqual(
                {item["quote"]: item["content_hash"] for item in provisions}, baseline_hashes,
                f"{role}: provenance hashes must be reordered, never rewritten",
            )
            for item in provisions:
                self.assertTrue(item["source"] and item["article"] and item["version"] and item["content_hash"])

    def test_missing_body_keeps_no_role_baseline(self) -> None:
        uploaded = self.upload()
        no_body = self.align(uploaded)
        empty_json = self.align(uploaded, body=b"{}", content_type="application/json")
        non_json_body = self.align(uploaded, body="user_role=出租人".encode("utf-8"), content_type="text/plain")

        for response in (no_body, empty_json, non_json_body):
            self.assertEqual(response["status"], 200, response)
        # No-role ordering: both provisions tie on retrieval score, so the
        # stable source tie-break keeps the lessor-side provision first.
        self.assertEqual(self.quotes(no_body["body"]), [LESSOR_QUOTE, TENANT_QUOTE])
        self.assertEqual(empty_json["body"]["findings"], no_body["body"]["findings"])
        self.assertEqual(non_json_body["body"]["findings"], no_body["body"]["findings"])
        for finding in no_body["body"]["findings"]:
            self.assertNotIn("user_role", finding["reasoning"])

    def test_unknown_role_is_rejected(self) -> None:
        uploaded = self.upload()
        response = self.align(
            uploaded,
            body=json.dumps({"user_role": "律师"}, ensure_ascii=False).encode("utf-8"),
            content_type="application/json",
        )

        self.assertEqual(response["status"], 400, response)
        self.assertEqual(response["body"]["error"]["code"], "invalid_request")


if __name__ == "__main__":
    unittest.main()
