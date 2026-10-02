from __future__ import annotations

import io
import json
import os
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from app.db import apply_migrations
from app.main import create_app


def multipart(text: bytes, *, filename: str = "lease.txt", file_type: str = "text/plain") -> tuple[bytes, str]:
    boundary = "phase2-boundary"
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


class Phase2AlignmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        # 隔离真实 Jev 凭证：align 判定会真实降级 not_found，套件必须是离线确定的。
        self._old_jev = {k: os.environ.pop(k, None) for k in ("CONTRACT_READER_JEV_API_KEY", "TYPESAFE_API_KEY")}
        self.app = create_app(Path(self.temp.name) / "app.db")

    def tearDown(self) -> None:
        for key, value in self._old_jev.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temp.cleanup()

    def upload(self, content: str, *, filename: str = "lease.txt", file_type: str = "text/plain") -> dict:
        body, content_type = multipart(content.encode("utf-8"), filename=filename, file_type=file_type)
        response = request(self.app, "POST", "/v1/contracts", body=body, content_type=content_type)
        self.assertEqual(response["status"], 200, response)
        return response["body"]

    def test_alignment_returns_versioned_legal_evidence_for_matching_finding(self) -> None:
        deposit = "押金为一个月租金，退租后七日内返还。"
        content = "\n".join((
            deposit,
            "未经出租人书面同意，承租人不得改造房屋。",
            "房屋及附属设施的日常维修由出租人负责。",
            "承租人提前退租，应提前三十日通知并承担违约金。",
        ))
        corpus = Path(self.temp.name) / "legal.jsonl"
        corpus.write_text(json.dumps({
            "source": "示范法规",
            "article": "第十条",
            "version": "2026-01-01",
            "quote": f"房屋租赁中，{deposit}",
        }, ensure_ascii=False) + "\n", encoding="utf-8")
        old = os.environ.get("CONTRACT_READER_LEGAL_CORPUS")
        os.environ["CONTRACT_READER_LEGAL_CORPUS"] = str(corpus)
        try:
            uploaded = self.upload(content)
            response = request(
                self.app,
                "POST",
                f"/v1/contracts/{uploaded['contract_id']}/versions/{uploaded['version_id']}/align",
            )
        finally:
            if old is None:
                os.environ.pop("CONTRACT_READER_LEGAL_CORPUS", None)
            else:
                os.environ["CONTRACT_READER_LEGAL_CORPUS"] = old

        self.assertEqual(response["status"], 200, response)
        payload = response["body"]
        self.assertEqual(payload["status"], "matched")
        findings = {item["type"]: item for item in payload["findings"]}
        matched = findings["deposit"]
        self.assertEqual(matched["alignment_status"], "matched")
        self.assertEqual(matched["contract_evidence"][0]["quote"], deposit)
        self.assertEqual(len(matched["legal_provisions"]), 1)
        provision = matched["legal_provisions"][0]
        self.assertEqual(provision["source"], "示范法规")
        self.assertEqual(provision["article"], "第十条")
        self.assertEqual(provision["version"], "2026-01-01")
        self.assertTrue(provision["content_hash"])
        self.assertTrue(provision["matched_terms"])
        self.assertEqual(findings["repair"]["alignment_status"], "not_found")
        self.assertEqual(findings["repair"]["legal_provisions"], [])

    def test_alignment_without_corpus_is_not_found_without_legal_conclusion(self) -> None:
        old = os.environ.pop("CONTRACT_READER_LEGAL_CORPUS", None)
        try:
            uploaded = self.upload("押金为一个月租金，退租后七日内返还。\n" + "其他租赁约定足够长。")
            response = request(
                self.app,
                "POST",
                f"/v1/contracts/{uploaded['contract_id']}/versions/{uploaded['version_id']}/align",
            )
        finally:
            if old is not None:
                os.environ["CONTRACT_READER_LEGAL_CORPUS"] = old

        self.assertEqual(response["status"], 200, response)
        payload = response["body"]
        self.assertEqual(payload["status"], "not_found")
        for finding in payload["findings"]:
            self.assertEqual(finding["alignment_status"], "not_found")
            self.assertEqual(finding["legal_provisions"], [])
        self.assertNotIn("legal_conclusion", json.dumps(payload, ensure_ascii=False))

    def test_alignment_keeps_needs_review_block_for_image_without_ocr(self) -> None:
        corpus = Path(self.temp.name) / "legal.jsonl"
        corpus.write_text(json.dumps({
            "source": "示范法规", "article": "第十条", "version": "2026-01-01",
            "quote": "押金为一个月租金",
        }, ensure_ascii=False) + "\n", encoding="utf-8")
        old = os.environ.get("CONTRACT_READER_LEGAL_CORPUS")
        os.environ["CONTRACT_READER_LEGAL_CORPUS"] = str(corpus)
        try:
            uploaded = self.upload("押金为一个月租金", filename="scan.png", file_type="image/png")
            response = request(
                self.app,
                "POST",
                f"/v1/contracts/{uploaded['contract_id']}/versions/{uploaded['version_id']}/align",
            )
        finally:
            if old is None:
                os.environ.pop("CONTRACT_READER_LEGAL_CORPUS", None)
            else:
                os.environ["CONTRACT_READER_LEGAL_CORPUS"] = old

        self.assertEqual(response["status"], 200, response)
        payload = response["body"]
        self.assertEqual(payload["status"], "needs_review")
        self.assertTrue(all(item["alignment_status"] == "needs_review" for item in payload["findings"]))
        self.assertTrue(all(item["legal_provisions"] == [] for item in payload["findings"]))

    def test_alignment_migration_creates_storage_table(self) -> None:
        db_path = Path(self.temp.name) / "migration.db"
        apply_migrations(db_path)
        with closing(sqlite3.connect(db_path)) as connection:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
        self.assertIn("legal_alignments", tables)


if __name__ == "__main__":
    unittest.main()
