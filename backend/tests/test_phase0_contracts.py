from __future__ import annotations

import io
import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from app.db import apply_migrations
from app.main import create_app
from app.schemas import Citation


class Response:
    def __init__(self, status_code: int, body: bytes):
        self.status_code = status_code
        self.text = body.decode("utf-8")

    def json(self):
        return json.loads(self.text)


def request(app, method: str, url: str, *, content: str | None = None,
            filename: str = "lease.txt", file_type: str = "text/plain",
            name: str = "示范租房合同") -> Response:
    body = b""
    content_type = ""
    if content is not None:
        boundary = "phase0-boundary"
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="name"\r\n\r\n{name}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {file_type}\r\n\r\n{content}\r\n--{boundary}--\r\n"
        ).encode("utf-8")
        content_type = f"multipart/form-data; boundary={boundary}"
    result = {}

    def start_response(status, headers):
        result["status"] = int(status.split()[0])

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": url,
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": content_type,
        "wsgi.input": io.BytesIO(body),
    }
    output = b"".join(app(environ, start_response))
    return Response(result["status"], output)


class Phase0Tests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "app.db"
        self.app = create_app(self.db_path)

    def tearDown(self):
        self.temp.cleanup()

    def upload_contract(self, content: str, filename: str = "lease.txt") -> dict:
        response = request(self.app, "POST", "/contracts", content=content, filename=filename)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_upload_creates_contract_version_and_page_text(self):
        payload = self.upload_contract("第一条\n押金为一个月租金。\n")
        self.assertTrue(payload["contract_id"])
        self.assertTrue(payload["version_id"])
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["page_count"], 1)

        response = request(
            self.app,
            "GET",
            f"/contracts/{payload['contract_id']}/versions/{payload['version_id']}",
        )
        self.assertEqual(response.status_code, 200)
        version = response.json()
        self.assertEqual(version["pages"][0]["page"], 1)
        self.assertIn("押金为一个月租金", version["pages"][0]["text"])

    def test_analyze_returns_four_clause_cards_with_verifiable_citations(self):
        payload = self.upload_contract(
            "押金为一个月租金，退租后七日内返还。\n"
            "未经出租人书面同意，承租人不得改造房屋。\n"
            "房屋及附属设施的日常维修由出租人负责。\n"
            "承租人提前退租，应提前三十日通知并承担违约金。\n",
        )
        response = request(
            self.app,
            "POST",
            f"/contracts/{payload['contract_id']}/versions/{payload['version_id']}/analyze",
        )
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["version_id"], payload["version_id"])
        findings = {finding["type"]: finding for finding in result["findings"]}
        self.assertEqual(set(findings), {"deposit", "modification", "repair", "early_termination"})
        for finding in findings.values():
            self.assertEqual(finding["status"], "confirmed")
            self.assertGreaterEqual(finding["confidence"], 0)
            self.assertLessEqual(finding["confidence"], 1)
            self.assertEqual(len(finding["contract_evidence"]), 1)
            evidence = finding["contract_evidence"][0]
            self.assertEqual(evidence["page"], 1)
            self.assertTrue(evidence["span_id"].startswith("p1-"))
            self.assertTrue(evidence["quote"])
            self.assertTrue(finding["action_card"]["question"])

    def test_missing_clause_is_explicitly_not_found_without_fake_citation(self):
        payload = self.upload_contract("本合同仅约定租金和租期。\n")
        response = request(
            self.app,
            "POST",
            f"/contracts/{payload['contract_id']}/versions/{payload['version_id']}/analyze",
        )
        self.assertEqual(response.status_code, 200)
        findings = {finding["type"]: finding for finding in response.json()["findings"]}
        self.assertEqual(findings["deposit"]["status"], "not_found")
        self.assertEqual(findings["deposit"]["contract_evidence"], [])
        self.assertIsNone(findings["deposit"]["action_card"])
        self.assertNotIn("法律", json.dumps(findings["deposit"], ensure_ascii=False))

    def test_invalid_upload_has_stable_error_without_echoing_contract_text(self):
        secret_text = "身份证号 110101199001010011"
        response = request(
            self.app,
            "POST",
            "/contracts",
            content=secret_text,
            filename="secret.json",
            file_type="application/json",
            name="secret",
        )
        self.assertEqual(response.status_code, 415)
        body = response.json()
        self.assertEqual(set(body), {"error"})
        self.assertEqual(body["error"]["code"], "unsupported_media_type")
        self.assertTrue(body["error"]["request_id"])
        self.assertNotIn(secret_text, response.text)

    def test_citation_schema_rejects_invalid_ranges(self):
        with self.assertRaises(ValueError):
            Citation(page=0, span_id="p0-s1", quote="bad")
        with self.assertRaises(ValueError):
            Citation(page=1, span_id="p1-s1", quote="")

    def test_initial_migration_creates_phase0_tables(self):
        db_path = Path(self.temp.name) / "migration.db"
        apply_migrations(db_path)
        with closing(sqlite3.connect(db_path)) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertTrue({"contracts", "contract_versions", "document_pages", "text_spans"} <= tables)


if __name__ == "__main__":
    unittest.main()
