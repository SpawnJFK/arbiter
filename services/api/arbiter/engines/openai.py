"""OpenAI Chat Completions client in JSON mode (LlmClient).

Only active when ARBITER_OPENAI_API_KEY is set. ``response_format={"type":"json_object"}``
makes the API guarantee syntactically valid JSON; we still parse defensively. Reasoning
models (gpt-5*, o-series) reject a custom temperature, so it is only sent to models that
accept it.
"""

from __future__ import annotations

from typing import Any

import httpx

from arbiter.config import Settings, get_settings
from arbiter.contracts import EngineError, Usage
from arbiter.engines.http import check_response, extract_json, with_retry
from arbiter.engines.pricing import estimate_cost

API_URL = "https://api.openai.com/v1/chat/completions"
_NO_TEMPERATURE_PREFIXES = ("gpt-5", "o1", "o3", "o4")


class OpenAiClient:
    name = "openai"

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
        self.api_key = s.openai_api_key if api_key is None else api_key
        self.model = model or s.openai_model
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
            raise EngineError("openai: no API key configured")
        # JSON mode requires the word "JSON" in the messages.
        sys_prompt = (
            system + (f"\n\nJSON schema: {schema_hint}" if schema_hint else "") + "\n\nAnswer in JSON."
        )
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
            "max_completion_tokens": max_tokens,
        }
        if not self.model.startswith(_NO_TEMPERATURE_PREFIXES):
            body["temperature"] = temperature
        headers = {"authorization": f"Bearer {self.api_key}", "content-type": "application/json"}
        usage_total = Usage()

        def call() -> tuple[dict[str, Any], str]:
            resp = self._client().post(API_URL, json=body, headers=headers)
            check_response(resp, "openai")
            data = resp.json()
            u = data.get("usage") or {}
            usage_total.input_tokens += int(u.get("prompt_tokens", 0))
            usage_total.output_tokens += int(u.get("completion_tokens", 0))
            choices = data.get("choices") or []
            if not choices:
                raise EngineError("openai: no choices in response")
            msg = choices[0].get("message") or {}
            if msg.get("refusal"):
                raise EngineError(f"openai: refusal: {msg['refusal']}")
            return extract_json(msg.get("content") or ""), str(data.get("model") or self.model)

        parsed, model_version = with_retry(call, attempts=self.attempts, backoff=self.backoff)
        usage_total.cost = estimate_cost(
            "openai",
            model=model_version,
            input_tokens=usage_total.input_tokens,
            output_tokens=usage_total.output_tokens,
        )
        return parsed, usage_total, model_version
