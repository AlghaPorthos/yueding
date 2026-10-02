import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.main import create_app


def request(app, method, path, payload=None, headers=None, body=None, content_type=None):
    if body is None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else b""
    result = {}
    content_type = content_type if content_type is not None else ("application/json" if payload is not None else "")

    def start_response(status, response_headers):
        result["status"] = int(status.split()[0])

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path.split("?", 1)[0],
        "QUERY_STRING": path.split("?", 1)[1] if "?" in path else "",
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": content_type,
        "wsgi.input": io.BytesIO(body),
    }
    for key, value in (headers or {}).items():
        environ["HTTP_" + key.upper().replace("-", "_")] = value
    result["body"] = json.loads(b"".join(app(environ, start_response)))
    return result


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.app = create_app(Path(self.temp.name) / "lifecycle.db")
        self.user = request(self.app, "POST", "/v1/users", {
            "display_name": "Alice", "email": "alice@example.test",
        })["body"]
        self.workspace = request(self.app, "POST", "/v1/workspaces", {
            "name": "Lease review", "owner_id": self.user["user_id"],
        })["body"]
        self.headers = {
            "X-User-ID": self.user["user_id"],
            "X-Workspace-ID": self.workspace["workspace_id"],
        }
        boundary = "lifecycle-boundary"
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="lease.txt"\r\nContent-Type: text/plain\r\n\r\n'
            "押金应在退租后七日内退还。维修由甲方负责。"
            f"\r\n--{boundary}--\r\n"
        ).encode()
        upload = request(
            self.app,
            "POST",
            "/v1/contracts",
            headers=self.headers,
            body=body,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        self.assertIn(upload["status"], {200, 201}, upload)
        self.contract = upload["body"]

    def tearDown(self):
        self.temp.cleanup()

    def test_reminder_and_checklist_are_persisted_and_can_be_completed(self):
        contract_id = self.contract["contract_id"]
        reminder = request(self.app, "POST", f"/v1/contracts/{contract_id}/reminders", {
            "title": "确认押金退还",
            "due_at": "2026-10-09T09:00:00+08:00",
            "version_id": self.contract["version_id"],
        }, headers=self.headers)
        self.assertEqual(reminder["status"], 201, reminder)
        self.assertEqual(reminder["body"]["status"], "pending")

        checklist = request(self.app, "POST", f"/v1/contracts/{contract_id}/checklist", {
            "title": "保存退租交接凭证",
            "due_at": "2026-10-08",
        }, headers=self.headers)
        self.assertEqual(checklist["status"], 201, checklist)
        item_id = checklist["body"]["item_id"]
        completed = request(self.app, "POST", f"/v1/checklist/{item_id}/complete", headers=self.headers)
        self.assertEqual(completed["status"], 200, completed)
        self.assertEqual(completed["body"]["status"], "completed")

        listed = request(self.app, "GET", f"/v1/contracts/{contract_id}/checklist", headers=self.headers)
        self.assertEqual(listed["status"], 200)
        self.assertEqual(listed["body"]["items"][0]["status"], "completed")

    def test_draft_versions_increment_and_keep_evidence(self):
        contract_id = self.contract["contract_id"]
        base_version = self.contract["version_id"]
        first = request(self.app, "POST", f"/v1/contracts/{contract_id}/drafts", {
            "base_version_id": base_version,
            "content": "请确认押金在退租后七日内结算，并提供书面凭证。",
            "source": "user",
            "evidence": [{"page": 1, "span_id": "p1-s1", "quote": "押金应在退租后七日内退还。"}],
        }, headers=self.headers)
        self.assertEqual(first["status"], 201, first)
        self.assertEqual(first["body"]["version_number"], 1)
        second = request(self.app, "POST", f"/v1/contracts/{contract_id}/drafts", {
            "base_version_id": base_version,
            "content": "补充结算凭证和异议期限。",
            "source": "user",
            "evidence": [],
        }, headers=self.headers)
        self.assertEqual(second["status"], 201, second)
        self.assertEqual(second["body"]["version_number"], 2)
        listed = request(self.app, "GET", f"/v1/contracts/{contract_id}/drafts", headers=self.headers)
        self.assertEqual(listed["status"], 200)
        self.assertEqual([item["version_number"] for item in listed["body"]["drafts"]], [2, 1])
        self.assertEqual(listed["body"]["drafts"][0]["evidence"], [])

    def test_lifecycle_requires_identity(self):
        response = request(self.app, "GET", f"/v1/contracts/{self.contract['contract_id']}/reminders")
        self.assertEqual(response["status"], 403)


if __name__ == "__main__":
    unittest.main()
