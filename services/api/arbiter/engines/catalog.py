"""What the platform can talk to: providers, their models, capabilities, regions, prices.

Served by GET /v1/engines/catalog and used by the credential endpoints to validate input.
`secret_fields` and `config_fields` drive the "add key" dialog in the web app; a secret
with several fields (AWS keys, a Google service account) is stored as one JSON string.
Prices come from pricing.py (estimates, see its docstring), never typed in twice.
"""

from __future__ import annotations

from typing import Any

from arbiter.engines.pricing import ENGINE_RATES, LLM_MODEL_RATES, TRAINING_RATES, Rate

PROVIDERS: dict[str, dict[str, Any]] = {
    "anthropic": {
        "name": "Anthropic API",
        "capabilities": ["llm", "mt"],
        "glossary": True,  # as llm-mt: terms go into the prompt
        "regions": ["global"],
        "models": ["claude-opus-5-5", "claude-sonnet-5", "claude-haiku-5"],
        "secret_fields": ["api_key"],
        "config_fields": ["model"],
    },
    "openai": {
        "name": "OpenAI API",
        "capabilities": ["llm", "mt"],
        "glossary": True,
        "regions": ["global"],
        "models": ["gpt-5", "gpt-5-mini"],
        "secret_fields": ["api_key"],
        "config_fields": ["model"],
    },
    "deepl": {
        "name": "DeepL API",
        "capabilities": ["mt"],
        "glossary": False,  # server-side glossaries only; enforced by hard checks
        "regions": ["eu"],
        "models": ["deepl-v2"],
        "secret_fields": ["api_key"],
        "config_fields": [],
    },
    "google": {
        "name": "Google Cloud Translation (Basic)",
        "capabilities": ["mt"],
        "glossary": False,
        "regions": ["global"],
        "models": ["nmt-v2"],
        "secret_fields": ["api_key"],
        "config_fields": [],
    },
    "bedrock": {
        "name": "Claude on AWS Bedrock",
        "capabilities": ["llm", "mt"],
        "glossary": True,
        "regions": ["eu", "us", "global"],
        "models": ["eu.anthropic.claude-opus-5", "eu.anthropic.claude-sonnet-5"],
        "secret_fields": ["access_key_id", "secret_access_key"],
        "config_fields": ["model", "aws_region"],
    },
    "vertex": {
        "name": "Claude on Google Vertex AI",
        "capabilities": ["llm", "mt"],
        "glossary": True,
        "regions": ["eu", "us", "global"],
        "models": ["claude-opus-5", "claude-sonnet-5"],
        "secret_fields": ["service_account_json"],
        "config_fields": ["model", "project", "location", "endpoint"],
    },
    "openai_compatible": {
        "name": "OpenAI-compatible endpoint",
        "capabilities": ["llm", "mt"],
        "glossary": True,
        "regions": ["eu", "us", "global"],
        "models": [],
        "secret_fields": ["api_key"],
        "config_fields": ["endpoint", "model", "region", "json_mode", "price_in_per_m", "price_out_per_m"],
    },
    "together": {
        "name": "Together AI (fine-tuning)",
        "capabilities": ["training"],
        "glossary": False,
        "regions": ["us"],
        "models": ["meta-llama/Llama-3.3-70B-Instruct-Reference", "Qwen/Qwen2.5-72B-Instruct"],
        "secret_fields": ["api_key"],
        "config_fields": [],
    },
    "fireworks": {
        "name": "Fireworks AI (fine-tuning)",
        "capabilities": ["training"],
        "glossary": False,
        "regions": ["us"],
        "models": ["accounts/fireworks/models/llama-v3p3-70b-instruct"],
        "secret_fields": ["api_key"],
        "config_fields": ["account_id"],
    },
}

TRAINING_PROVIDERS = ("together", "fireworks", "manual")


def _price(rate: Rate) -> dict[str, Any]:
    if rate.unit == "chars":
        return {"unit": "1M characters", "input": str(rate.input_per_m), "output": None}
    return {"unit": "1M tokens", "input": str(rate.input_per_m), "output": str(rate.output_per_m)}


def model_price(provider: str, model: str) -> dict[str, Any]:
    from arbiter.engines.pricing import rate_for

    return _price(rate_for(provider, model))


def catalog() -> list[dict[str, Any]]:
    out = []
    for key, p in PROVIDERS.items():
        entry: dict[str, Any] = {"provider": key, **p}
        if "training" in p["capabilities"]:
            entry["price"] = {"unit": "1M training tokens", "input": str(TRAINING_RATES[key]), "output": None}
            entry["model_prices"] = {}
        else:
            entry["price"] = _price(ENGINE_RATES.get(key, ENGINE_RATES["anthropic"]))
            entry["model_prices"] = {m: model_price(key, m) for m in p["models"]}
        out.append(entry)
    return out


def secret_from_fields(provider: str, fields: dict[str, str]) -> str:
    """Turn the dialog's secret fields into the one string that is encrypted."""
    import json

    wanted = PROVIDERS[provider]["secret_fields"]
    if wanted == ["api_key"]:
        return str(fields.get("api_key", "")).strip()
    if wanted == ["service_account_json"]:
        return str(fields.get("service_account_json", "")).strip()
    return json.dumps({k: str(fields.get(k, "")).strip() for k in wanted}, sort_keys=True)


__all__ = ["LLM_MODEL_RATES", "PROVIDERS", "TRAINING_PROVIDERS", "catalog", "secret_from_fields"]
