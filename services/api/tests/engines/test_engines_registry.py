from __future__ import annotations

from decimal import Decimal

import pytest

from arbiter.config import Settings, get_settings
from arbiter.contracts import EngineError
from arbiter.engines import registry
from arbiter.engines.anthropic import AnthropicClient
from arbiter.engines.deepl import DeepLEngine
from arbiter.engines.google import GoogleEngine
from arbiter.engines.mock import MockLlm, MockMt
from arbiter.engines.openai import OpenAiClient
from arbiter.engines.pricing import estimate_cost, rate_for


def test_env_is_test():
    assert get_settings().is_test


def test_registry_returns_only_mocks_in_test_env():
    assert isinstance(registry.get_mt("mock-mt"), MockMt)
    assert isinstance(registry.get_llm("mock-llm"), MockLlm)
    assert registry.get_mt("llm-mt:mock-llm").name == "llm-mt:mock-llm"
    for name in ("deepl", "google"):
        with pytest.raises(EngineError):
            registry.get_mt(name)
    for name in ("anthropic", "openai"):
        with pytest.raises(EngineError):
            registry.get_llm(name)
    with pytest.raises(EngineError):
        registry.get_mt("llm-mt:anthropic")
    assert registry.available_mt() == ["mock-mt", "llm-mt:mock-llm"]
    assert registry.available_llm() == ["mock-llm"]


def test_registry_mocks_only_even_with_keys_in_test_env():
    s = Settings(env="test", anthropic_api_key="k", openai_api_key="k", deepl_api_key="k", google_api_key="k")
    assert registry.available_mt(s) == ["mock-mt", "llm-mt:mock-llm"]
    with pytest.raises(EngineError):
        registry.get_mt("deepl", s)


def test_registry_outside_test_env_requires_keys():
    # No request is made: constructing a client does not touch the network.
    empty = Settings(env="dev", anthropic_api_key="", openai_api_key="", deepl_api_key="", google_api_key="")
    assert registry.available_mt(empty) == ["mock-mt", "llm-mt:mock-llm"]
    with pytest.raises(EngineError):
        registry.get_mt("deepl", empty)
    with pytest.raises(EngineError):
        registry.get_mt("nope", empty)
    keyed = Settings(
        env="dev", anthropic_api_key="a", openai_api_key="", deepl_api_key="d", google_api_key=""
    )
    assert set(registry.available_mt(keyed)) == {"mock-mt", "deepl", "llm-mt:mock-llm", "llm-mt:anthropic"}
    assert isinstance(registry.get_mt("deepl", keyed), DeepLEngine)
    assert isinstance(registry.get_llm("anthropic", keyed), AnthropicClient)


def test_available_false_without_key():
    s = Settings(env="test")
    assert not AnthropicClient(s).available()
    assert not OpenAiClient(s).available()
    assert not DeepLEngine(s).available()
    assert not GoogleEngine(s).available()


def test_pricing_estimates():
    assert estimate_cost("mock-mt", characters=1000) == Decimal("0")
    assert estimate_cost("deepl", characters=1_000_000) == Decimal("25")
    assert estimate_cost("anthropic", model="claude-opus-5-5", input_tokens=1_000_000) == Decimal("5")
    assert rate_for("openai", "gpt-5-mini-2026").input_per_m == Decimal("0.5")
    assert rate_for("llm-mt:anthropic").unit == "tokens"
    # rounding is UP so estimates never understate cost
    assert estimate_cost("deepl", characters=1) == Decimal("0.000025")
