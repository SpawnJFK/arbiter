"""Engine registry (R-MT-02 engine routing uses these names).

Names:
    mock-mt, mock-llm                 in-process mocks (region "local")
    anthropic, openai                 LLM APIs
    bedrock, vertex                   Claude through AWS Bedrock / Google Vertex (EU route, D-057)
    deepl, google                     classic MT
    compat:<credential id>            an OpenAI-compatible endpoint (vLLM, Mistral, hosted models)
    custom:<custom model id>          an org's own fine-tuned model (MT only)
    llm-mt:<llm name>                 any LLM above used as an MT engine

Credentials (D-056): with an EngineContext (session + org), each provider's key is
resolved org BYOK > platform key in the DB > environment; without one, the environment
only (the behaviour before D-056). Building a client never touches the network.

Safety rule: when settings.env == "test" ONLY mocks are handed out, whatever keys the
environment or the database holds. This is a second fence behind conftest blanking the
keys: a test can never reach a paid API, even if someone sets a key in their shell.
Provider clients are tested directly with stubbed transports (httpx.MockTransport,
botocore Stubber).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from arbiter.config import Settings, get_settings
from arbiter.contracts import EngineError, LlmClient, MtEngine
from arbiter.engines import credentials as creds
from arbiter.engines.anthropic import AnthropicClient
from arbiter.engines.bedrock import BedrockClient
from arbiter.engines.deepl import DeepLEngine
from arbiter.engines.google import GoogleEngine
from arbiter.engines.llm_mt import LlmMt
from arbiter.engines.mock import MockLlm, MockMt
from arbiter.engines.openai import OpenAiClient
from arbiter.engines.openai_compatible import CustomModelMt, OpenAiCompatibleClient
from arbiter.engines.vertex import VertexClient

MOCK_MT = ("mock-mt",)
MOCK_LLM = ("mock-llm",)
REAL_MT = ("deepl", "google")
REAL_LLM = ("anthropic", "openai", "bedrock", "vertex")
LLM_MT_PREFIX = "llm-mt:"
COMPAT_PREFIX = "compat:"
CUSTOM_PREFIX = "custom:"

# engine name -> provider (budgets, catalog). llm-mt:<x> is billed as <x>.
_PROVIDER_OF_PREFIX = {COMPAT_PREFIX: "openai_compatible", CUSTOM_PREFIX: "custom"}


def provider_of(name: str) -> str:
    if name.startswith(LLM_MT_PREFIX):
        return provider_of(name[len(LLM_MT_PREFIX) :])
    for prefix, provider in _PROVIDER_OF_PREFIX.items():
        if name.startswith(prefix):
            return provider
    if name.startswith("mock") or name == "scripted":
        return "mock"
    return name


@dataclass
class EngineContext:
    """Who the call is for. session None = environment keys only."""

    session: Session | None = None
    org_id: str | None = None
    _cache: dict[str, Any] = field(default_factory=dict, repr=False)

    def credential(self, provider: str, settings: Settings) -> creds.ResolvedCredential | None:
        if provider not in self._cache:
            self._cache[provider] = creds.resolve(self.session, self.org_id, provider, settings)
        return self._cache[provider]


def _settings(settings: Settings | None) -> Settings:
    return settings or get_settings()


def _ctx(context: EngineContext | None) -> EngineContext:
    return context or EngineContext()


def build_llm(provider: str, cred: creds.ResolvedCredential | None, settings: Settings) -> LlmClient:
    """Construct a client from a resolved credential. No network access."""
    config = cred.config if cred else {}
    secret = cred.secret if cred else ""
    if provider == "anthropic":
        return AnthropicClient(settings, api_key=secret, model=config.get("model") or None)
    if provider == "openai":
        return OpenAiClient(settings, api_key=secret, model=config.get("model") or None)
    if provider == "bedrock":
        keys = cred.secret_json() if cred else {}
        return BedrockClient(
            model=str(config.get("model") or settings.bedrock_model),
            aws_region=str(config.get("aws_region") or settings.bedrock_region),
            access_key_id=str(keys.get("access_key_id", "")),
            secret_access_key=str(keys.get("secret_access_key", "")),
            session_token=str(keys.get("session_token", "")),
        )
    if provider == "vertex":
        return VertexClient(
            service_account=secret,
            project=str(config.get("project") or ""),
            location=str(config.get("location") or settings.vertex_location),
            model=str(config.get("model") or settings.vertex_model),
            endpoint=str(config.get("endpoint") or ""),
        )
    if provider == "openai_compatible":
        name = f"{COMPAT_PREFIX}{cred.credential_id}" if cred and cred.credential_id else "openai_compatible"
        return OpenAiCompatibleClient.from_config(name, secret, config)
    raise EngineError(f"unknown llm {provider!r}")


def build_mt(provider: str, cred: creds.ResolvedCredential | None, settings: Settings) -> MtEngine:
    secret = cred.secret if cred else ""
    if provider == "deepl":
        return DeepLEngine(settings, api_key=secret)
    if provider == "google":
        return GoogleEngine(settings, api_key=secret)
    raise EngineError(f"unknown engine {provider!r}")


def get_llm(
    name: str, settings: Settings | None = None, *, context: EngineContext | None = None
) -> LlmClient:
    s = _settings(settings)
    ctx = _ctx(context)
    if name == "mock-llm":
        return MockLlm()
    if s.is_test:
        raise EngineError(f"llm {name!r} is not available in the test environment (mocks only)")
    client: LlmClient
    if name in REAL_LLM:
        client = build_llm(name, ctx.credential(name, s), s)
    elif name.startswith(COMPAT_PREFIX):
        cred_id = name[len(COMPAT_PREFIX) :]
        cred = creds.by_id(ctx.session, cred_id, ctx.org_id, s) if ctx.session is not None else None
        if cred is None or cred.provider != "openai_compatible":
            raise EngineError(f"llm {name!r} is not configured for this organization")
        client = build_llm("openai_compatible", cred, s)
    else:
        raise EngineError(f"unknown llm {name!r}")
    if not client.available():
        raise EngineError(f"llm {name!r} is not configured (missing credentials)")
    from arbiter.observability import ObservedLlm

    return ObservedLlm(client)  # usage events (no text) when PostHog is configured


def custom_model_engine(model: Any, cred: creds.ResolvedCredential | None) -> CustomModelMt:
    """MtEngine for a CustomModel row (also used by the training evaluation step)."""
    client = OpenAiCompatibleClient(
        name=model.engine_name,
        base_url=model.endpoint,
        api_key=cred.secret if cred else "",
        model=model.provider_model_id,
        region=model.region,
        json_mode=False,
    )
    return CustomModelMt(client, name=model.engine_name)


def get_mt(name: str, settings: Settings | None = None, *, context: EngineContext | None = None) -> MtEngine:
    s = _settings(settings)
    ctx = _ctx(context)
    if name == "mock-mt":
        return MockMt()
    if name.startswith(LLM_MT_PREFIX):
        return LlmMt(get_llm(name[len(LLM_MT_PREFIX) :], s, context=ctx))
    if s.is_test:
        raise EngineError(f"engine {name!r} is not available in the test environment (mocks only)")
    engine: MtEngine
    if name in REAL_MT:
        engine = build_mt(name, ctx.credential(name, s), s)
    elif name.startswith(CUSTOM_PREFIX):
        from arbiter.models import CustomModel

        model = ctx.session.get(CustomModel, name[len(CUSTOM_PREFIX) :]) if ctx.session is not None else None
        if model is None or model.org_id != ctx.org_id or not model.active:
            raise EngineError(f"engine {name!r} is not active for this organization")
        cred = creds.by_id(ctx.session, model.credential_id, ctx.org_id, s) if model.credential_id else None
        engine = custom_model_engine(model, cred)
    else:
        raise EngineError(f"unknown engine {name!r}")
    if not engine.available():
        raise EngineError(f"engine {name!r} is not configured (missing credentials)")
    from arbiter.observability import ObservedMt

    return ObservedMt(engine)


def available_llm(settings: Settings | None = None, *, context: EngineContext | None = None) -> list[str]:
    s = _settings(settings)
    ctx = _ctx(context)
    names = list(MOCK_LLM)
    if s.is_test:
        return names
    for n in REAL_LLM:
        cred = ctx.credential(n, s)
        if cred is not None and build_llm(n, cred, s).available():
            names.append(n)
    if ctx.session is not None:
        names += [f"{COMPAT_PREFIX}{c.id}" for c in creds.compat_credentials(ctx.session, ctx.org_id)]
    return names


def available_mt(settings: Settings | None = None, *, context: EngineContext | None = None) -> list[str]:
    s = _settings(settings)
    ctx = _ctx(context)
    names = list(MOCK_MT)
    if not s.is_test:
        names += [n for n in REAL_MT if ctx.credential(n, s) is not None]
        if ctx.session is not None and ctx.org_id:
            from sqlalchemy import select

            from arbiter.models import CustomModel

            names += [
                m.engine_name
                for m in ctx.session.execute(
                    select(CustomModel)
                    .where(CustomModel.org_id == ctx.org_id, CustomModel.active.is_(True))
                    .order_by(CustomModel.created_at)
                ).scalars()
            ]
    names += [LLM_MT_PREFIX + n for n in available_llm(s, context=ctx)]
    return names


def region_of(engine: Any) -> str:
    return str(getattr(engine, "region", "global"))
