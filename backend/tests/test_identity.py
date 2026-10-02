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
    request_headers = dict(headers or {})
    if content_type is None:
        content_type = "application/json" if payload is not None else ""

    def start_response(status, response_headers):
        result["status"] = int(status.split()[0])
        result["headers"] = dict(response_headers)

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path.split("?", 1)[0],
        "QUERY_STRING": path.split("?", 1)[1] if "?" in path else "",
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": content_type,
        "wsgi.input": io.BytesIO(body),
    }
    for key, value in request_headers.items():
        environ["HTTP_" + key.upper().replace("-", "_")] = value
    result["body"] = json.loads(b"".join(app(environ, start_response)))
    return result


class IdentityAndAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.app = create_app(Path(self.temp.name) / "identity.db")

    def tearDown(self):
        self.temp.cleanup()

    def create_user(self, display_name="Alice", email="alice@example.test"):
        response = request(self.app, "POST", "/v1/users", {
            "display_name": display_name,
            "email": email,
        })
        self.assertEqual(response["status"], 201, response)
        return response["body"]

    def create_workspace(self, user_id, name="Lease review"):
        response = request(self.app, "POST", "/v1/workspaces", {
            "name": name,
            "owner_id": user_id,
        })
        self.assertEqual(response["status"], 201, response)
        return response["body"]

    def scoped_headers(self, user_id, workspace_id):
        return {"X-User-ID": user_id, "X-Workspace-ID": workspace_id}

    def multipart(self, text, filename="lease.txt"):
        boundary = "identity-boundary"
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="{filename}"\r\nContent-Type: text/plain\r\n\r\n'
        ).encode() + text.encode() + f"\r\n--{boundary}--\r\n".encode()
        return body, f"multipart/form-data; boundary={boundary}"

    def test_scoped_contract_requires_workspace_membership_and_audit_is_redacted(self):
        owner = self.create_user()
        outsider = self.create_user("Bob", "bob@example.test")
        workspace = self.create_workspace(owner["user_id"])
        headers = self.scoped_headers(owner["user_id"], workspace["workspace_id"])
        body, content_type = self.multipart("押金 110101199001011234，联系电话 13800138000。")
        uploaded = request(self.app, "POST", "/v1/contracts", headers=headers, body=body, content_type=content_type)
        self.assertIn(uploaded["status"], {200, 201}, uploaded)
        contract = uploaded["body"]
        self.assertEqual(contract["workspace_id"], workspace["workspace_id"])

        version_path = f"/v1/contracts/{contract['contract_id']}/versions/{contract['version_id']}"
        denied = request(
            self.app, "GET", version_path,
            headers=self.scoped_headers(outsider["user_id"], workspace["workspace_id"]),
        )
        self.assertEqual(denied["status"], 403)
        self.assertEqual(denied["body"]["error"]["code"], "forbidden")

        events = request(
            self.app, "GET", "/v1/audit-events",
            headers=headers,
        )
        self.assertEqual(events["status"], 200, events)
        self.assertGreaterEqual(events["body"]["count"], 1)
        serialized = json.dumps(events["body"], ensure_ascii=False)
        self.assertNotIn("110101199001011234", serialized)
        self.assertNotIn("13800138000", serialized)
        self.assertIn("contract.upload", serialized)

    def test_non_member_cannot_create_workspace_for_another_user(self):
        owner = self.create_user()
        outsider = self.create_user("Bob", "bob@example.test")
        response = request(self.app, "POST", "/v1/workspaces", {
            "name": "Nope",
            "owner_id": owner["user_id"],
        }, headers={"X-User-ID": outsider["user_id"]})
        self.assertEqual(response["status"], 403)
        self.assertEqual(response["body"]["error"]["code"], "forbidden")

    def test_job_cannot_reference_a_contract_outside_the_requester_workspace(self):
        owner = self.create_user()
        outsider = self.create_user("Bob", "bob@example.test")
        workspace = self.create_workspace(owner["user_id"])
        body, content_type = self.multipart("维修由甲方负责。")
        uploaded = request(
            self.app, "POST", "/v1/contracts",
            headers={
                **self.scoped_headers(owner["user_id"], workspace["workspace_id"]),
                "Content-Type": content_type,
            },
            body=body,
            content_type=content_type,
        )
        self.assertIn(uploaded["status"], {200, 201}, uploaded)
        contract_id = uploaded["body"]["contract_id"]
        denied = request(
            self.app, "POST", "/v1/jobs",
            {"kind": "contract.analyze", "contract_id": contract_id},
            headers=self.scoped_headers(outsider["user_id"], workspace["workspace_id"]),
        )
        self.assertEqual(denied["status"], 403)


if __name__ == "__main__":
    unittest.main()
