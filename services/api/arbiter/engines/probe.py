"""POST .../engines/{id}/test: one tiny real call with a stored credential.

Production and dev make the call (a few tokens or one word). The test environment never
does: `run_probe` raises there, and tests replace it with a stub. The outcome is written to
the credential row (last_tested_at, last_test_ok, last_test_error) without the secret.
"""

from __future__ import annotations

import httpx

from arbiter.config import Settings
from arbiter.contracts import EngineError, MtRequest
from arbiter.engines import registry
from arbiter.engines.credentials import ResolvedCredential
from arbiter.engines.http import check_response

LLM_PROVIDERS = ("anthropic", "openai", "bedrock", "vertex", "openai_compatible")


def run_probe(provider: str, cred: ResolvedCredential, settings: Settings) -> str:
    """Returns a short description of what answered. Raises EngineError on failure."""
    if settings.is_test:
        raise EngineError("live engine tests are disabled in the test environment")
    if provider in LLM_PROVIDERS:
        client = registry.build_llm(provider, cred, settings)
        if not client.available():
            raise EngineError("credential incomplete")
        _, usage, model = client.complete_json(
            "You are a health check.", 'Reply with {"ok": true}.', max_tokens=20
        )
        return f"{model} answered ({usage.input_tokens + usage.output_tokens} tokens)"
    if provider in ("deepl", "google"):
        engine = registry.build_mt(provider, cred, settings)
        res = engine.translate([MtRequest("Hello", "en", "de")])[0]
        if res.error or not res.target_tagged:
            raise EngineError(res.error or "empty translation")
        return f"{res.model_version} answered"
    if provider == "together":
        resp = httpx.get(
            "https://api.together.xyz/v1/models",
            headers={"authorization": f"Bearer {cred.secret}"},
            timeout=30,
        )
        check_response(resp, "together")
        return "together key accepted"
    if provider == "fireworks":
        account = str(cred.config.get("account_id") or settings.fireworks_account_id)
        resp = httpx.get(
            f"https://api.fireworks.ai/v1/accounts/{account}/models",
            params={"pageSize": 1},
            headers={"authorization": f"Bearer {cred.secret}"},
            timeout=30,
        )
        check_response(resp, "fireworks")
        return "fireworks key accepted"
    raise EngineError(f"no test for provider {provider!r}")
