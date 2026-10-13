"""Cost ESTIMATES per engine.

These constants are deliberately conservative (rounded up from public list prices as of
Oct 2026) and exist so margins are never overstated before the owner configures real
contract prices. They are estimates, not invoices: the provider bill is the truth, and
the billing module should reconcile against it. Units are "currency units" (the
configured settings.currency); providers bill in USD/EUR and FX is ignored here, which
is acceptable because the rounding margin is larger than typical FX drift.

Two pricing shapes exist:
  * character-based MT (DeepL, Google): price per 1M source characters
  * token-based LLMs: price per 1M input tokens and per 1M output tokens
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_UP, Decimal
from typing import Literal

MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class Rate:
    unit: Literal["chars", "tokens"]
    input_per_m: Decimal  # per 1M chars (chars) or 1M input tokens (tokens)
    output_per_m: Decimal = Decimal("0")


# Model-level overrides for token pricing. Matched by prefix of the model id.
LLM_MODEL_RATES: dict[str, Rate] = {
    "claude-opus": Rate("tokens", Decimal("5"), Decimal("25")),
    "claude-sonnet": Rate("tokens", Decimal("3"), Decimal("15")),
    "claude-haiku": Rate("tokens", Decimal("1.2"), Decimal("6")),
    "gpt-5-mini": Rate("tokens", Decimal("0.5"), Decimal("4")),
    "gpt-5": Rate("tokens", Decimal("1.5"), Decimal("12")),
}

ENGINE_RATES: dict[str, Rate] = {
    "mock-mt": Rate("chars", Decimal("0")),
    "mock-llm": Rate("tokens", Decimal("0"), Decimal("0")),
    "deepl": Rate("chars", Decimal("25")),
    "google": Rate("chars", Decimal("22")),
    # Fallbacks when the model id is unknown: priced as the most expensive tier.
    "anthropic": Rate("tokens", Decimal("5"), Decimal("25")),
    "openai": Rate("tokens", Decimal("1.5"), Decimal("12")),
    # Claude through AWS Bedrock / Google Vertex: regional (EU) endpoints carry a premium
    # over the global list price, so the fallback is the top tier plus 10 %.
    "bedrock": Rate("tokens", Decimal("5.5"), Decimal("27.5")),
    "vertex": Rate("tokens", Decimal("5.5"), Decimal("27.5")),
    # Hosted or self-hosted open-weight models (vLLM, fine-tunes): override per credential
    # with config price_in_per_m / price_out_per_m when the contract price is known.
    "openai_compatible": Rate("tokens", Decimal("1"), Decimal("3")),
    "compat": Rate("tokens", Decimal("1"), Decimal("3")),
    "custom": Rate("tokens", Decimal("1"), Decimal("3")),
}

# Fine-tuning: price per 1M training tokens (tokens x epochs), conservative.
TRAINING_RATES: dict[str, Decimal] = {
    "together": Decimal("3"),
    "fireworks": Decimal("3"),
    "manual": Decimal("0"),
}


def _model_candidates(model: str) -> list[str]:
    """Bedrock ids ("eu.anthropic.claude-opus-5-v1:0") and path-style ids
    ("publishers/anthropic/models/claude-opus-5") are matched on their model part too."""
    out = [model]
    if "anthropic." in model:
        out.append(model.rsplit("anthropic.", 1)[1])
    if "/" in model:
        out.append(model.rsplit("/", 1)[1])
    return out


def rate_for(engine: str, model: str | None = None) -> Rate:
    if model:
        # longest prefix wins so "gpt-5-mini" is not priced as "gpt-5"
        for candidate in _model_candidates(model):
            for prefix in sorted(LLM_MODEL_RATES, key=len, reverse=True):
                if candidate.startswith(prefix):
                    return LLM_MODEL_RATES[prefix]
    base = engine.split(":", 1)[0]
    if base == "llm-mt" and ":" in engine:
        return rate_for(engine.split(":", 1)[1], model)
    return ENGINE_RATES.get(base, Rate("tokens", Decimal("5"), Decimal("25")))


def estimate_cost(
    engine: str,
    *,
    model: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    characters: int = 0,
    rate: Rate | None = None,
) -> Decimal:
    """Estimated cost, rounded UP to 6 decimals. ``rate`` overrides the table (contract price)."""
    rate = rate or rate_for(engine, model)
    if rate.unit == "chars":
        cost = Decimal(characters) * rate.input_per_m / MILLION
    else:
        cost = (
            Decimal(input_tokens) * rate.input_per_m + Decimal(output_tokens) * rate.output_per_m
        ) / MILLION
    return cost.quantize(Decimal("0.000001"), rounding=ROUND_UP)
