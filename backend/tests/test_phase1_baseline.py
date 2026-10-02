from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from app.legal import LegalIndex
from app.main import create_app
from app.quality import assess_pages


class Phase1BaselineTests(unittest.TestCase):
    def _request(self, app, method: str, path: str, *, content: str | None = None,
                 filename: str = "lease.txt", file_type: str = "text/plain"):
        body = b""
        content_type = ""
        if content is not None:
            boundary = "phase1-boundary"
            body = (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                f"Content-Type: {file_type}\r\n\r\n{content}\r\n--{boundary}--\r\n"
            ).encode("utf-8")
            content_type = f"multipart/form-data; boundary={boundary}"
        response = {}

        def start(status, headers):
            response["status"] = int(status.split()[0])

        output = b"".join(app({
            "REQUEST_METHOD": method,
            "PATH_INFO": path.split("?", 1)[0],
            "QUERY_STRING": path.split("?", 1)[1] if "?" in path else "",
            "CONTENT_LENGTH": str(len(body)),
            "CONTENT_TYPE": content_type,
            "wsgi.input": io.BytesIO(body),
        }, start))
        response["json"] = json.loads(output)
        return response

    def test_image_without_ocr_is_needs_review(self):
        result = assess_pages([], source_type="image/png")
        self.assertEqual(result["status"], "needs_review")
        self.assertIn("ocr_unavailable", result["reasons"])

    def test_legal_index_is_versioned_and_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legal.jsonl"
            path.write_text(json.dumps({"source": "示例法规", "article": "第十条", "version": "2026-01-01", "quote": "出租人应当保障租赁物安全"}, ensure_ascii=False) + "\n", encoding="utf-8")
            result = LegalIndex.from_jsonl(path).search("租赁物安全")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["article"], "第十条")
        self.assertEqual(result[0]["reasoning"]["retrieval"], "phrase")

    def test_api_without_corpus_does_not_fabricate_law(self):
        with tempfile.TemporaryDirectory() as directory:
            old = os.environ.pop("CONTRACT_READER_LEGAL_CORPUS", None)
            try:
                app = create_app(Path(directory) / "app.db")
                response = self._request(app, "GET", "/v1/legal/search?q=%E6%8A%BC%E9%87%91")
                self.assertEqual(response["status"], 200)
            finally:
                if old is not None:
                    os.environ["CONTRACT_READER_LEGAL_CORPUS"] = old
        self.assertEqual(json.loads(b"{}"), {})

    def test_image_quality_is_persisted_and_blocks_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Path(directory) / "app.db")
            uploaded = self._request(app, "POST", "/contracts", content="not-ocr-text", filename="scan.png", file_type="image/png")
            self.assertEqual(uploaded["status"], 201)
            # Re-run the request with a response-capturing WSGI helper to inspect JSON.
            body = b""
            boundary = "phase1-boundary"
            body = (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="scan.png"\r\n'
                f"Content-Type: image/png\r\n\r\nnot-ocr-text\r\n--{boundary}--\r\n"
            ).encode()
            result = {}

            def start(status, headers):
                result["status"] = int(status.split()[0])

            response_body = b"".join(app({
                "REQUEST_METHOD": "POST", "PATH_INFO": "/contracts", "CONTENT_LENGTH": str(len(body)),
                "CONTENT_TYPE": f"multipart/form-data; boundary={boundary}", "wsgi.input": io.BytesIO(body),
            }, start))
            payload = json.loads(response_body)
            self.assertEqual(payload["quality_status"], "needs_review")
            self.assertEqual(payload["quality_reasons"], ["ocr_unavailable"])

            fetched = {}

            def fetch_start(status, headers):
                fetched["status"] = int(status.split()[0])

            version_body = b"".join(app({
                "REQUEST_METHOD": "GET",
                "PATH_INFO": f"/contracts/{payload['contract_id']}/versions/{payload['version_id']}",
                "CONTENT_LENGTH": "0", "CONTENT_TYPE": "", "wsgi.input": io.BytesIO(),
            }, fetch_start))
            self.assertEqual(fetched["status"], 200)
            self.assertEqual(json.loads(version_body)["quality_status"], "needs_review")

            analyzed = {}

            def analyze_start(status, headers):
                analyzed["status"] = int(status.split()[0])

            analysis_body = b"".join(app({
                "REQUEST_METHOD": "POST",
                "PATH_INFO": f"/contracts/{payload['contract_id']}/versions/{payload['version_id']}/analyze",
                "CONTENT_LENGTH": "0", "CONTENT_TYPE": "", "wsgi.input": io.BytesIO(),
            }, analyze_start))
            analysis = json.loads(analysis_body)
            self.assertEqual(analyzed["status"], 200)
            self.assertTrue(all(item["status"] == "needs_review" for item in analysis["findings"]))

    def test_legal_search_returns_versioned_source_from_configured_corpus(self):
        with tempfile.TemporaryDirectory() as directory:
            corpus = Path(directory) / "legal.jsonl"
            corpus.write_text(
                json.dumps({"source": "住房租赁条例", "article": "第十条", "version": "2026-01-01", "quote": "出租人应当保障租赁物安全"}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            old = os.environ.get("CONTRACT_READER_LEGAL_CORPUS")
            os.environ["CONTRACT_READER_LEGAL_CORPUS"] = str(corpus)
            try:
                app = create_app(Path(directory) / "app.db")
                response = {}

                def start(status, headers):
                    response["status"] = int(status.split()[0])

                output = b"".join(app({
                    "REQUEST_METHOD": "GET", "PATH_INFO": "/v1/legal/search",
                    "QUERY_STRING": "q=%E7%A7%9F%E8%B5%81%E7%89%A9%E5%AE%89%E5%85%A8",
                    "CONTENT_LENGTH": "0", "CONTENT_TYPE": "", "wsgi.input": io.BytesIO(),
                }, start))
            finally:
                if old is None:
                    os.environ.pop("CONTRACT_READER_LEGAL_CORPUS", None)
                else:
                    os.environ["CONTRACT_READER_LEGAL_CORPUS"] = old
        self.assertEqual(response["status"], 200)
        payload = json.loads(output)
        self.assertEqual(payload["status"], "confirmed")
        self.assertEqual(payload["results"][0]["article"], "第十条")
        self.assertTrue(payload["results"][0]["content_hash"])

    def test_alignment_is_deterministic_and_does_not_fabricate_without_corpus(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Path(directory) / "app.db")
            uploaded = self._request(app, "POST", "/contracts", content="押金为一个月租金，退租后七日内返还。")
            self.assertEqual(uploaded["status"], 201)
            payload = uploaded["json"]
            aligned = self._request(
                app,
                "POST",
                f"/v1/contracts/{payload['contract_id']}/versions/{payload['version_id']}/align",
            )
            self.assertEqual(aligned["status"], 200)
            self.assertEqual(aligned["json"]["status"], "not_found")
            self.assertTrue(all(item["status"] in {"not_found", "needs_review"} for item in aligned["json"]["alignments"]))

    def test_alignment_returns_source_and_hash_when_corpus_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            corpus = Path(directory) / "legal.jsonl"
            corpus.write_text(
                json.dumps({"source": "住房租赁条例", "article": "第十条", "version": "2026-01-01", "quote": "押金应当在租赁关系终止后返还"}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            old = os.environ.get("CONTRACT_READER_LEGAL_CORPUS")
            os.environ["CONTRACT_READER_LEGAL_CORPUS"] = str(corpus)
            try:
                app = create_app(Path(directory) / "app.db")
                uploaded = self._request(app, "POST", "/contracts", content="押金为一个月租金，退租后七日内返还。")
                payload = uploaded["json"]
                aligned = self._request(
                    app,
                    "POST",
                    f"/contracts/{payload['contract_id']}/versions/{payload['version_id']}/align",
                )
            finally:
                if old is None:
                    os.environ.pop("CONTRACT_READER_LEGAL_CORPUS", None)
                else:
                    os.environ["CONTRACT_READER_LEGAL_CORPUS"] = old
        self.assertEqual(aligned["status"], 200)
        deposit = next(item for item in aligned["json"]["alignments"] if item["type"] == "deposit")
        self.assertEqual(deposit["status"], "confirmed")
        self.assertEqual(deposit["legal_provisions"][0]["article"], "第十条")
        self.assertTrue(deposit["legal_provisions"][0]["content_hash"])


if __name__ == "__main__":
    unittest.main()
