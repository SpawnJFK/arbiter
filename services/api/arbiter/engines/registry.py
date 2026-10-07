"""Engine registry (R-MT-02 engine routing uses these names).

Names: mock-mt, mock-llm, anthropic, openai, deepl, google, llm-mt:<llm name>.

Safety rule: when settings.env == "test" ONLY mocks are handed out, whatever keys the
environment holds. This is a second fence behind conftest blanking the keys: a test can
never reach a paid API, even if someone sets a key in their shell.
"""

from __future__ import annotations

from arbiter.config import Settings, get_settings
from arbiter.contracts import EngineError, LlmClient, MtEngine
from arbiter.engines.anthropic import AnthropicClient
from arbiter.engines.deepl import DeepLEngine
from arbiter.engines.google import GoogleEngine
from arbiter.engines.llm_mt import LlmMt
from arbiter.engines.mock import MockLlm, MockMt
from arbiter.engines.openai import OpenAiClient

MOCK_MT = ("mock-mt",)
MOCK_LLM = ("mock-llm",)
REAL_MT = ("deepl", "google")
REAL_LLM = ("anthropic", "openai")
LLM_MT_PREFIX = "llm-mt:"


def _settings(settings: Settings | None) -> Settings:
    return settings or get_settings()


def get_llm(name: str, settings: Settings | None = None) -> LlmClient:
    s = _settings(settings)
    if name == "mock-llm":
        return MockLlm()
    if s.is_test:
        raise EngineError(f"llm {name!r} is not available in the test environment (mocks only)")
    client: LlmClient
    if name == "anthropic":
        client = AnthropicClient(s)
    elif name == "openai":
        client = OpenAiClient(s)
    else:
        raise EngineError(f"unknown llm {name!r}")
    if not client.available():
        raise EngineError(f"llm {name!r} is not configured (missing API key)")
    return client


def get_mt(name: str, settings: Settings | None = None) -> MtEngine:
    s = _settings(settings)
    if name == "mock-mt":
        return MockMt()
    if name.startswith(LLM_MT_PREFIX):
        return LlmMt(get_llm(name[len(LLM_MT_PREFIX) :], s))
    if s.is_test:
        raise EngineError(f"engine {name!r} is not available in the test environment (mocks only)")
    engine: MtEngine
    if name == "deepl":
        engine = DeepLEngine(s)
    elif name == "google":
        engine = GoogleEngine(s)
    else:
        raise EngineError(f"unknown engine {name!r}")
    if not engine.available():
        raise EngineError(f"engine {name!r} is not configured (missing API key)")
    return engine


def available_llm(settings: Settings | None = None) -> list[str]:
    s = _settings(settings)
    names = list(MOCK_LLM)
    if not s.is_test:
        names += [
            n
            for n, ok in (("anthropic", bool(s.anthropic_api_key)), ("openai", bool(s.openai_api_key)))
            if ok
        ]
    return names


def available_mt(settings: Settings | None = None) -> list[str]:
    s = _settings(settings)
    names = list(MOCK_MT)
    if not s.is_test:
        names += [n for n, ok in (("deepl", bool(s.deepl_api_key)), ("google", bool(s.google_api_key))) if ok]
    names += [LLM_MT_PREFIX + n for n in available_llm(s)]
    return names
