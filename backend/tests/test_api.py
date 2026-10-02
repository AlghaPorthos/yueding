import io
import json
import logging
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app import main


def invoke(method, path, body=b"", content_type=""):
    result = {}

    def start_response(status, headers):
        result["status"] = int(status.split()[0])
        result["headers"] = dict(headers)

    environment = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": content_type,
        "wsgi.input": io.BytesIO(body),
    }
    result["body"] = b"".join(main.application(environment, start_response))
    return result


def multipart(text: bytes, filename="lease.txt", file_type="text/plain"):
    boundary = "test-boundary"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="{filename}"\r\nContent-Type: {file_type}\r\n\r\n'
    ).encode() + text + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        main._db_path = lambda: Path(self.tmp.name) / "contracts.sqlite3"
        main.init_db()

    def tearDown(self):
        self.tmp.cleanup()

    def test_health_upload_reference_and_duplicate(self):
        health = invoke("GET", "/healthz")
        self.assertEqual(health["status"], 200)
        body, content_type = multipart("甲方负责维修。\f乙方应按时支付租金。".encode())
        first = invoke("POST", "/v1/contracts", body, content_type)
        self.assertEqual(first["status"], 200)
        data = json.loads(first["body"])
        self.assertEqual(data["pages"][0]["span_id"], "p1-s1")
        self.assertEqual(data["pages"][1]["quote"], "乙方应按时支付租金。")
        fetched = invoke(
            "GET",
            f"/v1/contracts/{data['contract_id']}/versions/{data['version_id']}",
        )
        self.assertEqual(fetched["status"], 200)
        self.assertEqual(json.loads(fetched["body"])["pages"], data["pages"])
        duplicate = invoke("POST", "/v1/contracts", body, content_type)
        duplicate_data = json.loads(duplicate["body"])
        self.assertTrue(duplicate_data["duplicate"])
        self.assertEqual(duplicate_data["version_id"], data["version_id"])

    def test_invalid_errors_and_redacted_logging(self):
        body, content_type = multipart(b"hello", "x.exe", "application/octet-stream")
        unsupported = invoke("POST", "/v1/contracts", body, content_type)
        self.assertEqual(unsupported["status"], 400)
        self.assertEqual(
            json.loads(unsupported["body"])["error"]["code"], "unsupported_type"
        )
        body, content_type = multipart(b"   ")
        empty = invoke("POST", "/v1/contracts", body, content_type)
        self.assertEqual(json.loads(empty["body"])["error"]["code"], "empty_input")
        body, content_type = multipart(b"\xff\xfe")
        invalid = invoke("POST", "/v1/contracts", body, content_type)
        self.assertEqual(json.loads(invalid["body"])["error"]["code"], "parse_failed")

        secret = "身份证号 110101199001011234"
        with self.assertLogs("contract_reader", level=logging.INFO) as logs:
            body, content_type = multipart(secret.encode(), "secret.txt")
            result = invoke("POST", "/v1/contracts", body, content_type)
        self.assertEqual(result["status"], 200)
        self.assertNotIn(secret, "".join(logs.output))
        self.assertNotIn("secret.txt", "".join(logs.output))


if __name__ == "__main__":
    unittest.main()
