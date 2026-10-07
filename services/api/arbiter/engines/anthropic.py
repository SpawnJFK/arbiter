"""Anthropic Messages API client (LlmClient).

Only active when ARBITER_ANTHROPIC_API_KEY is set. JSON-only: the system prompt demands
a single JSON object and the reply is parsed with ``extract_json``; a reply that is not
JSON is retried (once per attempt budget) like a transient error, because in practice a
second sample almost always complies. 429 / 5xx / 529 overloaded are retried with
exponential backoff via tenacity.
"""

from __future__ import annotations

from typing import Any

import httpx

from arbiter.config import Settings, get_settings
from arbiter.contracts import EngineError, Usage
from arbiter.engines.http import check_response, extract_json, with_retry
from arbiter.engines.pricing import estimate_cost

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
JSON_ONLY = "\n\nRespond with a single JSON object only. No prose, no code fences."


class AnthropicClient:
    name = "anthropic"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        api_key: str | None = None,
        model: str | None = None,
        http_client: httpx.Client | None = None,
        attempts: int = 4,
        backoff: float = 1.0,
        timeout: float = 120.0,
    ) -> None:
        s = settings or get_settings()
        self.api_key = s.anthropic_api_key if api_key is None else api_key
        self.model = model or s.anthropic_model
        self._http = http_client
        self.attempts = attempts
        self.backoff = backoff
        self.timeout = timeout

    def available(self) -> bool:
        return bool(self.api_key)

    def _client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(timeout=self.timeout)
        return self._http

    def complete_json(
        self,
        system: str,
        user: str,
        *,
        schema_hint: str = "",
        max_tokens: int = 2000,
        temperature: float = 0.0,
    ) -> tuple[dict[str, Any], Usage, str]:
        if not self.available():
            raise EngineError("anthropic: no API key configured")
        sys_prompt = system + (f"\n\nJSON schema: {schema_hint}" if schema_hint else "") + JSON_ONLY
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": sys_prompt,
            "messages": [{"role": "user", "content": user}],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }
        usage_total = Usage()

        def call() -> tuple[dict[str, Any], str]:
            resp = self._client().post(API_URL, json=body, headers=headers)
            check_response(resp, "anthropic")
            data = resp.json()
            if data.get("type") == "error":
                raise EngineError(f"anthropic: {data.get('error')}")
            u = data.get("usage") or {}
            # Every attempt that reached the model is billed, so usage accumulates.
            usage_total.input_tokens += int(u.get("input_tokens", 0))
            usage_total.output_tokens += int(u.get("output_tokens", 0))
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            return extract_json(text), str(data.get("model") or self.model)

        parsed, model_version = with_retry(call, attempts=self.attempts, backoff=self.backoff)
        usage_total.cost = estimate_cost(
            "anthropic",
            model=model_version,
            input_tokens=usage_total.input_tokens,
            output_tokens=usage_total.output_tokens,
        )
        return parsed, usage_total, model_version
