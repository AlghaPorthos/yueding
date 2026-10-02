"""Evidence-constrained LLM providers with standard-library transport.

The application never discovers legal facts through this module.  Callers must
provide the already validated evidence set, and generated citations are checked
against that set before they can be returned to a client.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ProviderFailure(Exception):
    def __init__(self, code: str, message: str = "模型供应商不可用") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class LLMRequest:
    system: str
    user: str
    schema: dict[str, Any]
    max_tokens: int = 1200


@dataclass(frozen=True)
class LLMResult:
    content: str
    provider: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost: float | None = None
    latency_ms: int = 0


class LLMProvider(Protocol):
    name: str
    model: str

    def generate(self, request: LLMRequest) -> LLMResult:
        ...


class UnconfiguredProvider:
    name = "unconfigured"
    model = ""

    def generate(self, request: LLMRequest) -> LLMResult:
        del request
        raise ProviderFailure("not_configured", "未配置模型供应商")


class OpenAICompatibleProvider:
    """Minimal OpenAI-compatible chat completion client.

    API keys are held only in memory from environment configuration.  They are
    never included in errors, result objects, or logs.
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        model: str,
        *,
        name: str,
        timeout: float = 30.0,
        input_cost_per_1k: float = 0.0,
        output_cost_per_1k: float = 0.0,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.name = name
        self.timeout = timeout
        self.input_cost_per_1k = input_cost_per_1k
        self.output_cost_per_1k = output_cost_per_1k

    def generate(self, request: LLMRequest) -> LLMResult:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "temperature": 0,
            "max_tokens": request.max_tokens,
            "response_format": {"type": "json_object"},
        }
        started = time.monotonic()
        http_request = Request(
            self.endpoint,
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
            raise ProviderFailure(code) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ProviderFailure("provider_unreachable") from exc
        try:
            data = json.loads(raw.decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty completion")
            usage = data.get("usage") or {}
            input_tokens = usage.get("prompt_tokens")
            output_tokens = usage.get("completion_tokens")
            cost = None
            if isinstance(input_tokens, int) and isinstance(output_tokens, int):
                cost = (input_tokens / 1000) * self.input_cost_per_1k + (output_tokens / 1000) * self.output_cost_per_1k
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderFailure("invalid_provider_response") from exc
        return LLMResult(
            content=content,
            provider=self.name,
            model=self.model,
            input_tokens=input_tokens if isinstance(input_tokens, int) else None,
            output_tokens=output_tokens if isinstance(output_tokens, int) else None,
            estimated_cost=cost,
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
        )


class AnthropicCompatibleProvider:
    """Minimal Anthropic Messages API client for coding-plan endpoints.

    GLM-5.x models emit ``thinking`` blocks before the text block, so the
    token budget is padded to keep the JSON answer from being truncated.
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        model: str,
        *,
        name: str,
        timeout: float = 30.0,
        disable_thinking: bool = False,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.name = name
        self.timeout = timeout
        self.disable_thinking = disable_thinking

    def generate(self, request: LLMRequest) -> LLMResult:
        payload = {
            "model": self.model,
            "max_tokens": request.max_tokens + (1000 if not self.disable_thinking else 200),
            "system": request.system,
            "messages": [{"role": "user", "content": request.user}],
            "temperature": 0,
        }
        if self.disable_thinking:
            payload["thinking"] = {"type": "disabled"}
        started = time.monotonic()
        http_request = Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(http_request, timeout=self.timeout) as response:
                raw = response.read(4 * 1024 * 1024)
        except HTTPError as exc:
            code = "rate_limited" if exc.code == 429 else ("provider_http_error" if exc.code >= 500 else "provider_rejected")
            raise ProviderFailure(code) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ProviderFailure("provider_unreachable") from exc
        try:
            data = json.loads(raw.decode("utf-8"))
            content = data.get("content")
            text = "".join(
                str(block.get("text") or "")
                for block in (content if isinstance(content, list) else [])
                if isinstance(block, dict) and block.get("type") == "text"
            )
            if not text.strip():
                raise ValueError("empty completion")
            usage = data.get("usage") or {}
            input_tokens = usage.get("input_tokens")
            output_tokens = usage.get("output_tokens")
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderFailure("invalid_provider_response") from exc
        return LLMResult(
            content=text,
            provider=self.name,
            model=str(data.get("model") or self.model),
            input_tokens=input_tokens if isinstance(input_tokens, int) else None,
            output_tokens=output_tokens if isinstance(output_tokens, int) else None,
            estimated_cost=0.0,
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
        )


class StaticProvider:
    """Deterministic provider used by tests and local contract demonstrations."""

    def __init__(self, response: dict[str, Any], *, name: str = "static", model: str = "fixture") -> None:
        self.response = response
        self.name = name
        self.model = model

    def generate(self, request: LLMRequest) -> LLMResult:
        del request
        return LLMResult(
            content=json.dumps(self.response, ensure_ascii=False, separators=(",", ":")),
            provider=self.name,
            model=self.model,
            input_tokens=None,
            output_tokens=None,
            estimated_cost=0.0,
        )


class LLMRouter:
    """Try providers in order, with a per-request token/cost budget."""

    def __init__(self, providers: list[LLMProvider], *, max_cost: float = 0.50, validator: Callable[[str], Any] | None = None) -> None:
        self.providers = providers or [UnconfiguredProvider()]
        self.max_cost = max(0.0, max_cost)
        self.validator = validator

    @classmethod
    def from_env(cls) -> "LLMRouter":
        import os

        providers: list[LLMProvider] = []
        timeout = float(os.environ.get("CONTRACT_READER_LLM_TIMEOUT_SECONDS", "30"))
        # Keep the explicit project variables authoritative, while allowing the
        # local Z.AI setup to power the ordinary LLM path without copying a key
        # into another config file. Z.AI's v4 base URL exposes the OpenAI
        # compatible chat-completions route used by this provider.
        zai_key = os.environ.get("ZAI_API_KEY")
        zai_endpoint = os.environ.get("ZAI_API_URL") or os.environ.get("ZAI_BASE_URL")
        if zai_endpoint and not zai_endpoint.rstrip("/").endswith("/chat/completions"):
            zai_endpoint = zai_endpoint.rstrip("/") + "/chat/completions"
        zai_endpoint = zai_endpoint or "https://open.bigmodel.cn/api/paas/v4/chat/completions"
        zai_model = os.environ.get("ZAI_MODEL") or os.environ.get("GLM_MODEL") or "glm-5.3-flash"
        for prefix, name in (("CONTRACT_READER_LLM_PRIMARY", "primary"), ("CONTRACT_READER_LLM_FALLBACK", "fallback")):
            endpoint = os.environ.get(f"{prefix}_URL")
            model = os.environ.get(f"{prefix}_MODEL")
            api_key = os.environ.get(f"{prefix}_API_KEY")
            if prefix == "CONTRACT_READER_LLM_PRIMARY" and zai_key:
                endpoint = endpoint or zai_endpoint
                model = model or zai_model
                api_key = api_key or zai_key
            if endpoint and model and api_key:
                kind = os.environ.get(f"{prefix}_KIND", "openai").strip().lower()
                if kind == "anthropic":
                    providers.append(AnthropicCompatibleProvider(
                        endpoint, api_key, model, name=name, timeout=timeout,
                        disable_thinking=os.environ.get(f"{prefix}_THINKING", "").strip().lower() == "disabled",
                    ))
                else:
                    providers.append(OpenAICompatibleProvider(endpoint, api_key, model, name=name, timeout=timeout))
        try:
            max_cost = float(os.environ.get("CONTRACT_READER_LLM_MAX_COST", "0.50"))
        except ValueError:
            max_cost = 0.50
        return cls(providers, max_cost=max_cost)

    def describe(self) -> dict[str, Any]:
        return {
            "providers": [{"name": provider.name, "model": provider.model} for provider in self.providers],
            "configured": any(provider.name != "unconfigured" for provider in self.providers),
            "max_cost": self.max_cost,
        }

    def generate(self, request: LLMRequest, validator: Callable[[str], Any] | None = None) -> LLMResult:
        failures: list[ProviderFailure] = []
        output_validator = validator or self.validator
        for provider in self.providers:
            try:
                result = provider.generate(request)
                if result.estimated_cost is not None and result.estimated_cost > self.max_cost:
                    raise ProviderFailure("budget_exceeded", "模型调用超过预算")
                if output_validator is not None:
                    output_validator(result.content)
                return result
            except ProviderFailure as exc:
                failures.append(exc)
                continue
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                failures.append(ProviderFailure("invalid_output"))
                del exc
                continue
        if failures:
            raise failures[-1]
        raise ProviderFailure("not_configured")


def validate_generated_json(content: str, allowed_citations: list[dict[str, Any]], allowed_provisions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Validate the public generation schema, citation references, and legal refs."""
    try:
        value = json.loads(content)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("generated output is not JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("generated output must be an object")
    summary = value.get("summary")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 8000:
        raise ValueError("summary is invalid")
    severity = value.get("severity", "unknown")
    if severity not in {"low", "medium", "high", "unknown"}:
        raise ValueError("severity is invalid")
    for field in ("consequences", "actions"):
        items = value.get(field, [])
        if not isinstance(items, list) or any(not isinstance(item, str) or len(item) > 1000 for item in items):
            raise ValueError(f"{field} is invalid")
    citations = value.get("citations", [])
    if not isinstance(citations, list) or len(citations) > 100:
        raise ValueError("citations are invalid")
    # Providers may quote one sentence from a page-level evidence span. Keep
    # page/span identity strict and only accept text contained in the
    # server-authorized quote for that span.
    allowed: dict[tuple[Any, Any], list[str]] = {}
    for item in allowed_citations:
        key = (item.get("page"), item.get("span_id"))
        quote = item.get("quote")
        if isinstance(quote, str) and quote.strip():
            allowed.setdefault(key, []).append(quote.strip())
    # 越界引用直接剔除而不是整体拒绝：摘要与合法引用仍然可用。
    checked_citations: list[dict[str, Any]] = []
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        page = citation.get("page")
        span_id = citation.get("span_id")
        quote = citation.get("quote")
        if not isinstance(quote, str) or not quote.strip():
            continue
        authorized_quotes = allowed.get((page, span_id), [])
        normalized_quote = quote.strip()
        if any(normalized_quote == authorized or normalized_quote in authorized for authorized in authorized_quotes):
            checked_citations.append({"page": page, "span_id": span_id, "quote": normalized_quote})
    # Legal references must come from the server-provided corpus provisions.
    provision_quotes = [
        str(item.get("quote") or "").strip()
        for item in (allowed_provisions or [])
        if isinstance(item, dict) and str(item.get("quote") or "").strip()
    ]
    raw_legal_refs = value.get("legal_refs", [])
    checked_legal_refs: list[dict[str, Any]] = []
    if isinstance(raw_legal_refs, list):
        for ref in raw_legal_refs[:10]:
            if not isinstance(ref, dict):
                continue
            ref_quote = str(ref.get("quote") or "").strip()
            if ref_quote and any(ref_quote in provision or provision in ref_quote for provision in provision_quotes):
                checked_legal_refs.append({"article": str(ref.get("article") or "").strip(), "quote": ref_quote})
    value["severity"] = severity
    value["consequences"] = value.get("consequences", [])
    value["actions"] = value.get("actions", [])
    value["citations"] = checked_citations
    value["legal_refs"] = checked_legal_refs
    return value
