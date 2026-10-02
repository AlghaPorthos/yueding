"""Tests for the TypeSafe SystemOne judge provider against a local HTTP stub."""

from __future__ import annotations

import json
import socketserver
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from app.judge import JudgeError, JudgeResult, SystemOneProvider

QUESTIONS: dict[str, dict[str, Any]] = {
    "risky": {"type": "noul", "instructions": "clause risk", "criteria": "unbounded liability"},
    "verdict": {"type": "choice", "instructions": "overall verdict", "criteria": "reject / accept"},
    "severity": {"type": "score", "instructions": "severity", "criteria": "0-10"},
}

CANNED_RESPONSE: dict[str, Any] = {
    "model": "jev-1.13.0",
    "answers": {
        "risky": {"type": "noul", "noul": 0.82},
        "verdict": {
            "type": "choice",
            "choice": "reject",
            "confidence": 0.91,
            "probabilities": {"accept": 0.09, "reject": 0.91},
        },
        "severity": {
            "type": "score",
            "score": 7.5,
            "confidence": 0.88,
            "legend": {"min": 0, "max": 10},
            "probabilities": {"<=3": 0.05, "4-7": 0.35, ">=8": 0.60},
        },
    },
    "usage": {"input_tokens": 120, "output_tokens": 30},
}


class StubHandler(BaseHTTPRequestHandler):
    status = 200
    body = json.dumps(CANNED_RESPONSE).encode("utf-8")
    last_request: dict[str, Any] = {}

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length") or 0)
        StubHandler.last_request = {
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "content_type": self.headers.get("Content-Type"),
            "payload": json.loads(self.rfile.read(length).decode("utf-8")),
        }
        self.send_response(StubHandler.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(StubHandler.body)))
        self.end_headers()
        self.wfile.write(StubHandler.body)

    def log_message(self, *args: Any) -> None:
        pass


class QuietHTTPServer(HTTPServer):
    """HTTPServer whose bind skips ``socket.getfqdn`` (slow on some hosts)."""

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)


class SystemOneProviderTest(unittest.TestCase):
    def setUp(self) -> None:
        StubHandler.status = 200
        StubHandler.body = json.dumps(CANNED_RESPONSE).encode("utf-8")
        StubHandler.last_request = {}
        self.server = QuietHTTPServer(("127.0.0.1", 0), StubHandler)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def _provider(self, **env: str) -> SystemOneProvider:
        defaults = {"CONTRACT_READER_JEV_URL": self.base_url, "CONTRACT_READER_JEV_API_KEY": "test-key"}
        defaults.update(env)
        return SystemOneProvider.from_env(defaults)

    def test_judge_parses_answers_and_usage(self) -> None:
        result = self._provider(model="jev-latest").judge("合同状态文本", QUESTIONS)
        self.assertIsInstance(result, JudgeResult)
        self.assertEqual(result.model, "jev-1.13.0")
        self.assertEqual(result.input_tokens, 120)
        self.assertEqual(result.output_tokens, 30)
        self.assertEqual(result.answers["risky"]["type"], "noul")
        self.assertAlmostEqual(result.answers["risky"]["noul"], 0.82)
        self.assertEqual(result.answers["verdict"]["type"], "choice")
        self.assertEqual(result.answers["verdict"]["choice"], "reject")
        self.assertAlmostEqual(result.answers["verdict"]["confidence"], 0.91)
        self.assertEqual(result.answers["verdict"]["probabilities"], {"accept": 0.09, "reject": 0.91})
        self.assertEqual(result.answers["severity"]["type"], "score")
        self.assertAlmostEqual(result.answers["severity"]["score"], 7.5)
        self.assertAlmostEqual(result.answers["severity"]["confidence"], 0.88)
        self.assertEqual(result.answers["severity"]["legend"], {"min": 0, "max": 10})
        # Request contract: endpoint, auth, and verbatim state/model/questions.
        self.assertEqual(StubHandler.last_request["path"], "/systemone")
        self.assertEqual(StubHandler.last_request["authorization"], "Bearer test-key")
        self.assertEqual(StubHandler.last_request["content_type"], "application/json")
        payload = StubHandler.last_request["payload"]
        self.assertEqual(payload["model"], "jev-latest")
        self.assertEqual(payload["state"], "合同状态文本")
        self.assertEqual(payload["questions"], QUESTIONS)

    def test_judge_http_500_raises_judge_error(self) -> None:
        StubHandler.status = 500
        StubHandler.body = b'{"error": "internal"}'
        with self.assertRaises(JudgeError) as ctx:
            self._provider().judge("state", {"q": {"type": "noul"}})
        self.assertEqual(ctx.exception.code, "provider_http_error")

    def test_judge_malformed_response_raises_judge_error(self) -> None:
        StubHandler.body = b"not json at all"
        with self.assertRaises(JudgeError) as ctx:
            self._provider().judge("state", {"q": {"type": "noul"}})
        self.assertEqual(ctx.exception.code, "invalid_provider_response")

    def test_judge_without_api_key_is_inert(self) -> None:
        provider = SystemOneProvider.from_env({"CONTRACT_READER_JEV_URL": self.base_url})
        self.assertEqual(provider.api_key, "")
        with self.assertRaises(JudgeError) as ctx:
            provider.judge("state", QUESTIONS)
        self.assertEqual(ctx.exception.code, "not_configured")
        self.assertEqual(StubHandler.last_request, {})


if __name__ == "__main__":
    unittest.main()
