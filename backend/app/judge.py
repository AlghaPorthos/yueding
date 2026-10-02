"""TypeSafe SystemOne judgment provider (standard-library transport only).

The SystemOne API is a direct judgment endpoint, not OpenAI chat completions:
one state plus a set of typed questions goes in, and one typed answer per
question comes back.  This module keeps the HTTP and parsing contract in one
place so callers only ever see ``JudgeResult`` or ``JudgeError``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "https://api.typesafe.ai/v1"
DEFAULT_MODEL = "jev-latest"

_ANSWER_TYPES = ("noul", "choice", "score")


class JudgeError(Exception):
    """Raised for any provider failure; the caller decides the fallback."""

    def __init__(self, code: str, message: str = "判定服务不可用") -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class JudgeResult:
    model: str
    answers: dict[str, dict[str, Any]] = field(default_factory=dict)
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class SystemOneProvider:
    """Minimal client for ``POST {base_url}/systemone``.

    API keys are held only in memory from environment configuration.  They are
    never included in errors, result objects, or logs, and judged contract
    text is never echoed into exceptions.
    """

    base_url: str
    api_key: str
    model: str = DEFAULT_MODEL
    timeout: float = 5.0

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "SystemOneProvider":
        source = os.environ if env is None else env
        base_url = source.get("CONTRACT_READER_JEV_URL") or DEFAULT_BASE_URL
        model = source.get("CONTRACT_READER_JEV_MODEL") or DEFAULT_MODEL
        api_key = source.get("CONTRACT_READER_JEV_API_KEY") or source.get("TYPESAFE_API_KEY") or ""
        return cls(base_url=base_url, api_key=api_key, model=model)

    def judge(self, state: str, questions: dict[str, dict[str, Any]]) -> JudgeResult:
        if not self.api_key:
            raise JudgeError("not_configured", "未配置判定服务 API key")
        if not isinstance(questions, dict) or not questions:
            raise JudgeError("invalid_request", "questions 必须是非空字典")
        payload = {"state": state, "model": self.model, "questions": questions}
        http_request = Request(
            self.base_url.rstrip("/") + "/systemone",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(http_request, timeout=self.timeout) as response:
                raw = response.read(2 * 1024 * 1024)
        except HTTPError as exc:
            code = "rate_limited" if exc.code == 429 else ("provider_http_error" if exc.code >= 500 else "provider_rejected")
            raise JudgeError(code, f"HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise JudgeError("provider_unreachable", type(exc).__name__) from exc
        try:
            data = json.loads(raw.decode("utf-8"))
            answers = _parse_answers(data, questions)
            model = data["model"]
            if not isinstance(model, str) or not model:
                raise ValueError("missing model")
            usage = data.get("usage") or {}
            input_tokens = usage.get("input_tokens")
            output_tokens = usage.get("output_tokens")
            if not (input_tokens is None or isinstance(input_tokens, int)):
                raise ValueError("bad input_tokens")
            if not (output_tokens is None or isinstance(output_tokens, int)):
                raise ValueError("bad output_tokens")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise JudgeError("invalid_provider_response", str(exc) or type(exc).__name__) from exc
        return JudgeResult(
            model=model,
            answers=answers,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


def _parse_answers(data: Any, questions: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Validate the answer map against the asked questions and answer shapes."""
    if not isinstance(data, dict):
        raise ValueError("response is not an object")
    answers = data["answers"]
    if not isinstance(answers, dict):
        raise ValueError("answers is not an object")
    missing = [name for name in questions if name not in answers]
    if missing:
        raise ValueError("missing answers: " + ",".join(sorted(missing)))
    for name, answer in answers.items():
        if not isinstance(answer, dict) or answer.get("type") not in _ANSWER_TYPES:
            raise ValueError(f"bad answer type for {name!r}")
        if not isinstance(answer.get(answer["type"]), (int, float, str)):
            raise ValueError(f"bad answer value for {name!r}")
    return answers
