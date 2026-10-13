"""Generic OpenAI-compatible chat endpoint (LlmClient) and the custom-model MT engine.

OpenAiCompatibleClient: base_url + key + model, POST {base_url}/chat/completions. Used for
self-hosted vLLM, hosted fine-tunes (Together, Fireworks), Mistral and any provider that
speaks the Chat Completions protocol. The admin declares the region (where the endpoint
processes data) in the credential config; the default is "global", so an endpoint is only
used for EU processing when someone has said it runs in the EU. JSON mode is on by default
(`json_mode: false` in config for servers that reject response_format).

CustomModelMt: an org's own fine-tuned model as an MtEngine (`custom:<id>`). It speaks the
exact chat format the model was trained on (arbiter.training.dataset): tags as <gN>..</gN>
and <xN/>, the source as the user turn, the translation as the assistant turn.
"""

from __future__ import annotations

import html
import re
from decimal import Decimal
from typing import Any

import httpx

from arbiter.contracts import EngineError, MtRequest, MtResult, Usage
from arbiter.engines import tags
from arbiter.engines.http import check_response, extract_json, with_retry
from arbiter.engines.pricing import Rate, estimate_cost


def _rate_from_config(config: dict[str, Any]) -> Rate | None:
    pin, pout = config.get("price_in_per_m"), config.get("price_out_per_m")
    if pin is None and pout is None:
        return None
    return Rate("tokens", Decimal(str(pin or "0")), Decimal(str(pout or "0")))


class OpenAiCompatibleClient:
    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        region: str = "global",
        json_mode: bool = True,
        rate: Rate | None = None,
        http_client: httpx.Client | None = None,
        attempts: int = 4,
        backoff: float = 1.0,
        timeout: float = 120.0,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.region = region if region in ("eu", "us", "global") else "global"
        self.json_mode = json_mode
        self.rate = rate
        self._http = http_client
        self.attempts = attempts
        self.backoff = backoff
        self.timeout = timeout

    @classmethod
    def from_config(cls, name: str, secret: str, config: dict[str, Any], **kw: Any) -> OpenAiCompatibleClient:
        return cls(
            name=name,
            base_url=str(config.get("endpoint") or ""),
            api_key=secret,
            model=str(config.get("model") or ""),
            region=str(config.get("region") or "global"),
            json_mode=bool(config.get("json_mode", True)),
            rate=_rate_from_config(config),
            **kw,
        )

    def available(self) -> bool:
        return bool(self.base_url and self.model)

    def _client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(timeout=self.timeout)
        return self._http

    def chat(
        self, messages: list[dict[str, str]], *, max_tokens: int, temperature: float, json_mode: bool
    ) -> tuple[str, Usage, str]:
        """One chat completion with retries. Returns (content, usage, model)."""
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        usage_total = Usage()

        def call() -> tuple[str, str]:
            resp = self._client().post(f"{self.base_url}/chat/completions", json=body, headers=headers)
            check_response(resp, self.name)
            data = resp.json()
            u = data.get("usage") or {}
            usage_total.input_tokens += int(u.get("prompt_tokens", 0))
            usage_total.output_tokens += int(u.get("completion_tokens", 0))
            choices = data.get("choices") or []
            if not choices:
                raise EngineError(f"{self.name}: no choices in response")
            return str((choices[0].get("message") or {}).get("content") or ""), str(
                data.get("model") or self.model
            )

        content, model = with_retry(call, attempts=self.attempts, backoff=self.backoff)
        usage_total.cost = estimate_cost(
            self.name,
            model=None,
            input_tokens=usage_total.input_tokens,
            output_tokens=usage_total.output_tokens,
            rate=self.rate,
        )
        return content, usage_total, model

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
            raise EngineError(f"{self.name}: endpoint or model not configured")
        sys_prompt = (
            system + (f"\n\nJSON schema: {schema_hint}" if schema_hint else "") + "\n\nAnswer in JSON."
        )
        messages = [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user}]
        usage_total = Usage()

        def call() -> tuple[dict[str, Any], str]:
            content, used, model = self.chat(
                messages, max_tokens=max_tokens, temperature=temperature, json_mode=self.json_mode
            )
            usage_total.input_tokens += used.input_tokens
            usage_total.output_tokens += used.output_tokens
            usage_total.cost += used.cost
            return extract_json(content), model

        # chat() already retries transport errors; this outer loop gives a bad-JSON reply one more try.
        parsed, model = with_retry(call, attempts=2, backoff=self.backoff)
        return parsed, usage_total, model


# ------------------------------------------------------------------ custom models (training format)

TRAINING_SYSTEM = (
    "Translate the user's text from {source_lang} to {target_lang}. Keep every tag such as "
    "<g1>...</g1> or <x2/> exactly once and around the matching words. Answer with the "
    "translation only."
)
_TRAIN_TAG_RE = re.compile(r"<(/?)([gx])([A-Za-z0-9_.-]+)(/?)>")


def to_training_text(tagged: str) -> str:
    """⟦1⟧a⟦/1⟧ ⟦2/⟧ -> <g1>a</g1> <x2/>. Text is HTML-escaped so a literal '<' in the
    source can never be mistaken for a tag."""
    out: list[str] = []
    for kind, value in tags.pieces(tagged):
        if kind == "text":
            assert isinstance(value, str)
            out.append(html.escape(value, quote=False))
            continue
        assert isinstance(value, tuple)
        cid, ckind = value
        out.append({"open": f"<g{cid}>", "close": f"</g{cid}>"}.get(ckind, f"<x{cid}/>"))
    return "".join(out)


def from_training_text(text: str) -> str:
    """Inverse of to_training_text. Unknown markup stays as (escaped) text; tag QA judges it."""
    out: list[str] = []
    pos = 0
    for m in _TRAIN_TAG_RE.finditer(text):
        out.append(tags.escape_text(html.unescape(text[pos : m.start()])))
        pos = m.end()
        closing, kind, cid, selfclose = m.groups()
        if kind == "x":
            out.append(f"⟦{cid}/⟧")
        elif closing:
            out.append(f"⟦/{cid}⟧")
        elif selfclose:
            out.append(f"⟦{cid}/⟧")
        else:
            out.append(f"⟦{cid}⟧")
    out.append(tags.escape_text(html.unescape(text[pos:])))
    return "".join(out)


class CustomModelMt:
    supports_glossary = False  # terms are enforced afterwards by the hard checks

    def __init__(self, client: OpenAiCompatibleClient, *, name: str, max_tokens: int = 2000) -> None:
        self.client = client
        self.name = name
        self.region = client.region
        self.max_tokens = max_tokens

    def available(self) -> bool:
        return self.client.available()

    def translate(self, requests: list[MtRequest]) -> list[MtResult]:
        results: list[MtResult] = []
        for req in requests:
            messages = [
                {
                    "role": "system",
                    "content": TRAINING_SYSTEM.format(
                        source_lang=req.source_lang, target_lang=req.target_lang
                    ),
                },
                {"role": "user", "content": to_training_text(req.source_tagged)},
            ]
            try:
                content, usage, model = self.client.chat(
                    messages, max_tokens=self.max_tokens, temperature=0.0, json_mode=False
                )
            except EngineError as e:
                results.append(MtResult("", self.name, "", error=str(e)))
                continue
            results.append(MtResult(from_training_text(content.strip()), self.name, model, usage))
        return results
