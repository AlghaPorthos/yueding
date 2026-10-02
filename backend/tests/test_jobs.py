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


def request(app, method: str, path: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else b""
    result: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        result["status"] = int(status.split()[0])

    output = b"".join(app({
        "REQUEST_METHOD": method,
        "PATH_INFO": path.split("?", 1)[0],
        "QUERY_STRING": path.split("?", 1)[1] if "?" in path else "",
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": "application/json" if payload is not None else "",
        "wsgi.input": io.BytesIO(body),
    }, start_response))
    result["body"] = json.loads(output)
    return result


class JobApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "jobs.db"
        self.app = create_app(self.db_path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def create_job(self, **overrides: object) -> dict:
        payload = {"kind": "contract.parse", "payload": {"version": "v1"}}
        payload.update(overrides)
        response = request(self.app, "POST", "/v1/jobs", payload)
        self.assertIn(response["status"], {200, 201}, response)
        return response["body"]

    def test_migration_creates_jobs_and_attempts_tables(self) -> None:
        migration_path = Path(self.temp.name) / "migration.db"
        apply_migrations(migration_path)
        with closing(sqlite3.connect(migration_path)) as connection:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
        self.assertTrue({"jobs", "job_attempts"} <= tables)

    def test_create_get_list_and_idempotency_persist_job(self) -> None:
        created = self.create_job(idempotency_key="job-key-1", contract_id="contract-1")
        self.assertEqual(created["status"], "queued")
        self.assertEqual(created["attempts"], [])
        self.assertEqual(created["contract_id"], "contract-1")

        fetched = request(self.app, "GET", f"/v1/jobs/{created['job_id']}")
        self.assertEqual(fetched["status"], 200)
        self.assertEqual(fetched["body"]["job_id"], created["job_id"])
        self.assertEqual(fetched["body"]["payload"], {"version": "v1"})

        listed = request(self.app, "GET", "/v1/jobs?status=queued&limit=10")
        self.assertEqual(listed["status"], 200)
        self.assertEqual([item["job_id"] for item in listed["body"]["jobs"]], [created["job_id"]])

        duplicate = self.create_job(idempotency_key="job-key-1", contract_id="contract-1")
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["job_id"], created["job_id"])

        conflict = request(self.app, "POST", "/v1/jobs", {
            "kind": "contract.extract",
            "payload": {"version": "v2"},
            "idempotency_key": "job-key-1",
        })
        self.assertEqual(conflict["status"], 409)
        self.assertEqual(conflict["body"]["error"]["code"], "idempotency_conflict")

    def test_claim_fail_retry_and_status_persist_attempts(self) -> None:
        created = self.create_job(max_attempts=2)
        claimed = request(self.app, "POST", f"/v1/jobs/{created['job_id']}/claim", {
            "worker_id": "worker-a",
            "lease_seconds": 60,
        })
        self.assertEqual(claimed["status"], 200)
        self.assertEqual(claimed["body"]["status"], "running")
        self.assertEqual(len(claimed["body"]["attempts"]), 1)
        self.assertEqual(claimed["body"]["attempts"][0]["status"], "running")

        failed = request(self.app, "POST", f"/v1/jobs/{created['job_id']}/status", {
            "status": "failed",
            "error_code": "parse_failed",
            "error_message": "parse failed",
        })
        self.assertEqual(failed["status"], 200)
        self.assertEqual(failed["body"]["status"], "failed")
        self.assertEqual(failed["body"]["attempts"][0]["error_code"], "parse_failed")

        retried = request(self.app, "POST", f"/v1/jobs/{created['job_id']}/retry", {})
        self.assertEqual(retried["status"], 200)
        self.assertEqual(retried["body"]["status"], "queued")
        claimed_again = request(self.app, "POST", f"/v1/jobs/{created['job_id']}/run", {
            "worker_id": "worker-b",
        })
        self.assertEqual(claimed_again["status"], 200)
        self.assertEqual(len(claimed_again["body"]["attempts"]), 2)
        succeeded = request(self.app, "POST", f"/v1/jobs/{created['job_id']}/status", {
            "status": "succeeded",
            "progress": 100,
        })
        self.assertEqual(succeeded["status"], 200)
        self.assertEqual(succeeded["body"]["status"], "succeeded")
        self.assertEqual(succeeded["body"]["attempts"][-1]["status"], "succeeded")

    def test_cancel_recover_stale_and_stable_errors(self) -> None:
        queued = self.create_job()
        canceled = request(self.app, "POST", f"/v1/jobs/{queued['job_id']}/cancel", {})
        self.assertEqual(canceled["status"], 200)
        self.assertEqual(canceled["body"]["status"], "canceled")
        terminal_cancel = request(self.app, "POST", f"/v1/jobs/{queued['job_id']}/cancel", {})
        self.assertEqual(terminal_cancel["status"], 409)
        self.assertEqual(terminal_cancel["body"]["error"]["code"], "invalid_job_transition")

        stale = self.create_job()
        claimed = request(self.app, "POST", f"/v1/jobs/{stale['job_id']}/claim", {"worker_id": "worker-a"})
        self.assertEqual(claimed["body"]["status"], "running")
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                "UPDATE jobs SET lease_until = '2000-01-01T00:00:00+00:00' WHERE id = ?",
                (stale["job_id"],),
            )
            connection.commit()
        recovered = request(self.app, "POST", "/v1/jobs/recover-stale", {"limit": 10})
        self.assertEqual(recovered["status"], 200)
        self.assertEqual(recovered["body"]["recovered"], [stale["job_id"]])
        recovered_job = request(self.app, "GET", f"/v1/jobs/{stale['job_id']}")
        self.assertEqual(recovered_job["body"]["status"], "queued")
        self.assertEqual(recovered_job["body"]["attempts"][0]["status"], "failed")

        missing = request(self.app, "GET", "/v1/jobs/missing")
        self.assertEqual(missing["status"], 404)
        self.assertEqual(set(missing["body"]), {"error"})
        self.assertEqual(missing["body"]["error"]["code"], "job_not_found")

        invalid = request(self.app, "POST", "/v1/jobs", {"payload": {}})
        self.assertEqual(invalid["status"], 400)
        self.assertEqual(invalid["body"]["error"]["code"], "invalid_request")


    def test_migration_persists_retry_schedule_events_and_dead_letter_fields(self) -> None:
        migration_path = Path(self.temp.name) / "phase6.db"
        apply_migrations(migration_path)
        with closing(sqlite3.connect(migration_path)) as connection:
            job_columns = {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}
            event_columns = {row[1] for row in connection.execute("PRAGMA table_info(job_events)")}
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertTrue({"next_attempt_at", "timeout_seconds", "dead_letter_at"} <= job_columns)
        self.assertIn("job_events", tables)
        self.assertTrue({"id", "job_id", "event_type", "progress", "payload"} <= event_columns)

    def test_failure_records_progress_event_and_exponential_retry_schedule(self) -> None:
        created = self.create_job(max_attempts=3)
        job_id = created["job_id"]
        self.assertEqual(request(self.app, "POST", f"/v1/jobs/{job_id}/claim", {"worker_id": "worker-a"})["status"], 200)
        failed = request(self.app, "POST", f"/v1/jobs/{job_id}/status", {
            "status": "failed",
            "error_code": "temporary_failure",
            "progress": 40,
        })
        self.assertEqual(failed["status"], 200)
        self.assertIsNotNone(failed["body"]["next_attempt_at"])
        self.assertEqual(failed["body"]["events"][-1]["event_type"], "failed")
        self.assertEqual(failed["body"]["events"][-1]["progress"], 40)
        retried = request(self.app, "POST", f"/v1/jobs/{job_id}/retry", {})
        self.assertEqual(retried["status"], 200)
        self.assertEqual(retried["body"]["status"], "queued")
        self.assertIsNotNone(retried["body"]["next_attempt_at"])

    def test_startup_recovers_expired_running_job(self) -> None:
        created = self.create_job()
        job_id = created["job_id"]
        self.assertEqual(request(self.app, "POST", f"/v1/jobs/{job_id}/claim", {"worker_id": "worker-a"})["status"], 200)
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute("UPDATE jobs SET lease_until = '2000-01-01T00:00:00+00:00' WHERE id = ?", (job_id,))
            connection.commit()
        restarted = create_app(self.db_path)
        recovered = request(restarted, "GET", f"/v1/jobs/{job_id}")
        self.assertEqual(recovered["body"]["status"], "queued")
        self.assertEqual(recovered["body"]["attempts"][0]["error_code"], "lease_expired")

 
if __name__ == "__main__":
    unittest.main()
