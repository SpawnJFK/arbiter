"""Credential resolution (D-051), routing precedence and the region / budget filters (D-053, R-MT-02)."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from arbiter import crypto
from arbiter.config import Settings
from arbiter.contracts import EngineError
from arbiter.engines import budgets, credentials, manage, registry, routing
from arbiter.engines.anthropic import AnthropicClient
from arbiter.engines.bedrock import BedrockClient
from arbiter.engines.errors import BudgetExceeded, NoEngineInRegion
from arbiter.engines.openai_compatible import OpenAiCompatibleClient
from arbiter.engines.vertex import VertexClient
from arbiter.models import EngineCredential, EngineScore, Organization

DEV = Settings(
    env="dev",
    anthropic_api_key="env-anthropic",
    openai_api_key="",
    deepl_api_key="",
    google_api_key="",
    aws_access_key_id="",
    aws_secret_access_key="",
    vertex_service_account_json="",
)

REGIONS = {
    "mock-mt": "local",
    "deepl": "eu",
    "google": "global",
    "llm-mt:anthropic": "global",
    "llm-mt:bedrock": "eu",
    "anthropic": "global",
    "bedrock": "eu",
    "vertex": "eu",
    "openai": "global",
}


def lookup(name: str) -> str | None:
    return REGIONS.get(name, "global")


def org(db, slug="acme", **settings) -> Organization:
    o = Organization(name=slug, slug=slug, settings=settings)
    db.add(o)
    db.flush()
    return o


def cred(
    db, provider, secret, *, scope="platform", org_id=None, config=None, enabled=True
) -> EngineCredential:
    c = EngineCredential(
        scope=scope,
        org_id=org_id,
        provider=provider,
        label=provider,
        secret_encrypted=crypto.encrypt(secret),
        secret_hint=crypto.hint(secret),
        config=config or {},
        enabled=enabled,
    )
    db.add(c)
    db.flush()
    return c


# ------------------------------------------------------------------ crypto


def test_crypto_roundtrip_rotation_and_prod_requires_key():
    s_old = Settings(env="dev", secrets_key="old-key-material")
    token = crypto.encrypt("sk-live-1234", s_old)
    assert "sk-live" not in token
    s_rot = Settings(env="dev", secrets_key="new-key-material,old-key-material")
    assert crypto.decrypt(token, s_rot) == "sk-live-1234"
    with pytest.raises(crypto.SecretsUnavailable):
        crypto.decrypt(token, Settings(env="dev", secrets_key="other"))
    with pytest.raises(crypto.SecretsUnavailable):
        crypto.encrypt("x", Settings(env="prod", secrets_key=""))
    assert crypto.hint("sk-live-1234") == "...1234"


def test_hint_for_multi_field_secrets():
    assert credentials.hint_for("bedrock", json.dumps({"secret_access_key": "abcdWXYZ"})) == "...WXYZ"
    assert credentials.hint_for("vertex", json.dumps({"private_key_id": "kid9876"})) == "...9876"


# ------------------------------------------------------------------ resolution


def test_resolution_org_beats_platform_beats_env(db):
    a, b = org(db, "a"), org(db, "b")
    assert credentials.resolve(db, a.id, "anthropic", DEV).source == "env"
    cred(db, "anthropic", "platform-key", config={"model": "claude-sonnet-5"})
    r = credentials.resolve(db, a.id, "anthropic", DEV)
    assert (r.source, r.secret, r.config["model"]) == ("platform", "platform-key", "claude-sonnet-5")
    cred(db, "anthropic", "byok-a", scope="org", org_id=a.id)
    assert credentials.resolve(db, a.id, "anthropic", DEV).secret == "byok-a"
    # another org never sees a's key
    assert credentials.resolve(db, b.id, "anthropic", DEV).secret == "platform-key"
    # disabled keys are ignored
    cred(db, "anthropic", "byok-b-off", scope="org", org_id=b.id, enabled=False)
    assert credentials.resolve(db, b.id, "anthropic", DEV).secret == "platform-key"
    assert credentials.source_of(db, a.id, "anthropic", DEV) == "org"
    assert credentials.source_of(db, b.id, "anthropic", DEV) == "platform"
    assert credentials.source_of(db, b.id, "deepl", DEV) == "none"


def test_registry_builds_clients_from_resolved_credentials_without_network(db):
    a = org(db, "a")
    cred(db, "anthropic", "byok-a", scope="org", org_id=a.id, config={"model": "claude-haiku-5"})
    cred(
        db,
        "bedrock",
        json.dumps({"access_key_id": "AKID", "secret_access_key": "SECRET"}),
        config={"model": "eu.anthropic.claude-opus-5", "aws_region": "eu-central-1"},
    )
    sa = json.dumps({"client_email": "x@y", "private_key": "pem", "project_id": "p"})
    cred(db, "vertex", sa, config={"model": "claude-opus-5", "location": "eu"})
    compat = cred(
        db,
        "openai_compatible",
        "sk-c",
        scope="org",
        org_id=a.id,
        config={"endpoint": "https://eu.example.com/v1", "model": "m", "region": "eu"},
    )
    ctx = registry.EngineContext(db, a.id)
    llm = registry.get_llm("anthropic", DEV, context=ctx)
    assert isinstance(llm, AnthropicClient) and llm.api_key == "byok-a" and llm.model == "claude-haiku-5"
    bed = registry.get_llm("bedrock", DEV, context=ctx)
    assert isinstance(bed, BedrockClient) and bed.region == "eu"
    vx = registry.get_llm("vertex", DEV, context=ctx)
    assert isinstance(vx, VertexClient) and vx.region == "eu"
    cc = registry.get_llm(f"compat:{compat.id}", DEV, context=ctx)
    assert isinstance(cc, OpenAiCompatibleClient) and cc.region == "eu"
    names = registry.available_mt(DEV, context=ctx)
    for n in ("llm-mt:anthropic", "llm-mt:bedrock", "llm-mt:vertex", f"llm-mt:compat:{compat.id}"):
        assert n in names
    # another org cannot use a's compat endpoint
    other = org(db, "b")
    with pytest.raises(EngineError):
        registry.get_llm(f"compat:{compat.id}", DEV, context=registry.EngineContext(db, other.id))


def test_test_env_fence_holds_with_db_credentials(db):
    a = org(db, "a")
    cred(db, "anthropic", "byok-a", scope="org", org_id=a.id)
    ctx = registry.EngineContext(db, a.id)
    assert registry.available_llm(context=ctx) == ["mock-llm"]
    with pytest.raises(EngineError):
        registry.get_llm("anthropic", context=ctx)


def test_provider_of():
    assert registry.provider_of("llm-mt:anthropic") == "anthropic"
    assert registry.provider_of("compat:ecr_1") == "openai_compatible"
    assert registry.provider_of("llm-mt:compat:ecr_1") == "openai_compatible"
    assert registry.provider_of("custom:cmd_1") == "custom"
    assert registry.provider_of("mock-mt") == "mock"
    assert registry.provider_of("deepl") == "deepl"


# ------------------------------------------------------------------ routing precedence


def choose(db, o, purpose="mt", available=None, **kw):
    return routing.choose(
        db,
        org=o,
        purpose=purpose,
        source_lang=kw.pop("source_lang", "en"),
        target_lang=kw.pop("target_lang", "de"),
        content_type=kw.pop("content_type", "legal"),
        available=available or ["mock-mt", "deepl", "google", "llm-mt:anthropic", "llm-mt:bedrock"],
        region_lookup=lookup,
        **kw,
    )


def test_r_mt_02_default_then_scoreboard(db):
    o = org(db)
    c = choose(db, o)
    assert c.engines[0] == "mock-mt" and c.source == "default"
    db.add(
        EngineScore(
            engine="google",
            source_lang="en",
            target_lang="de",
            domain="legal",
            segments_measured=250,
            mean_qe=91,
        )
    )
    db.add(
        EngineScore(
            engine="deepl",
            source_lang="en",
            target_lang="de",
            domain="general",
            segments_measured=900,
            mean_qe=88,
        )
    )
    db.add(
        EngineScore(
            engine="llm-mt:anthropic",
            source_lang="en",
            target_lang="de",
            domain="legal",
            segments_measured=20,
            mean_qe=99,
        )
    )
    db.flush()
    c = choose(db, o)
    assert c.engines[:3] == ["google", "deepl", "mock-mt"]  # too few segments for anthropic to rank
    assert c.source == "scoreboard"


def test_route_precedence_specific_beats_general_and_org_beats_platform(db):
    o, other = org(db, "a"), org(db, "b")
    db.add(
        EngineScore(
            engine="google",
            source_lang="en",
            target_lang="de",
            domain="legal",
            segments_measured=500,
            mean_qe=95,
        )
    )
    manage.create_route(db, None, {"engines": ["llm-mt:anthropic"]})  # platform, general
    c = choose(db, o)
    assert c.engines[0] == "llm-mt:anthropic" and c.source == "route"
    assert c.engines[1] == "google"  # fallback continues with the scoreboard
    manage.create_route(db, None, {"engines": ["deepl"], "target_lang": "de"})  # platform, specific
    assert choose(db, o).engines[0] == "deepl"
    org_route = manage.create_route(db, o.id, {"engines": ["llm-mt:bedrock"]})  # org, general
    assert choose(db, o).engines[0] == "llm-mt:bedrock"
    assert choose(db, other).engines[0] == "deepl"  # another org's rule never applies
    manage.create_route(
        db,
        o.id,
        {"engines": ["google", "deepl"], "source_lang": "en", "target_lang": "de", "fallback": False},
    )
    c = choose(db, o)
    assert c.engines == ["google", "deepl"] and c.route_id != org_route.id
    # a rule for another content type does not match
    assert choose(db, o, content_type="general").engines[0] == "google"
    manage.update_route(org_route, {"enabled": False})
    # disabled rules are skipped
    assert choose(db, o, target_lang="fr").engines[0] == "llm-mt:anthropic"


def test_route_engines_that_are_unavailable_are_skipped(db):
    o = org(db)
    manage.create_route(db, o.id, {"engines": ["llm-mt:openai", "deepl"], "fallback": False})
    c = choose(db, o)
    assert c.engines == ["deepl"] and c.skipped["llm-mt:openai"] == "unavailable"


def test_senate_and_editor_fall_back_to_judge_route(db):
    o = org(db)
    avail = ["mock-llm", "anthropic", "bedrock"]
    manage.create_route(db, o.id, {"purpose": "judge", "engines": ["bedrock"]})
    assert choose(db, o, purpose="senate", available=avail).engines[0] == "bedrock"
    manage.create_route(db, o.id, {"purpose": "editor", "engines": ["anthropic"]})
    assert choose(db, o, purpose="editor", available=avail).engines[0] == "anthropic"
    assert choose(db, o, purpose="judge", available=avail).engines[0] == "bedrock"


# ------------------------------------------------------------------ EU processing


def test_eu_org_only_gets_eu_engines_and_never_falls_back(db):
    o = org(db, processing_region="eu")
    c = choose(db, o)
    assert set(c.engines) <= {"mock-mt", "deepl", "llm-mt:bedrock"}
    assert c.skipped["google"] == "region" and c.skipped["llm-mt:anthropic"] == "region"
    manage.create_route(db, o.id, {"engines": ["llm-mt:anthropic"], "fallback": False})
    with pytest.raises(NoEngineInRegion, match="no EU engine configured"):
        choose(db, o)


def test_eu_org_without_eu_engine_fails(db):
    o = org(db, processing_region="eu")
    with pytest.raises(NoEngineInRegion) as e:
        choose(db, o, purpose="judge", available=["anthropic", "openai"])
    assert e.value.code == "no_eu_engine"
    assert choose(db, o, purpose="judge", available=["anthropic", "vertex"]).engines == ["vertex"]
    g = org(db, "g", processing_region="global")
    assert choose(db, g, purpose="judge", available=["anthropic", "vertex"]).engines[0] == "anthropic"


def test_unknown_region_value_is_global(db):
    assert routing.processing_region(org(db, processing_region="mars")) == "global"


# ------------------------------------------------------------------ budgets


def test_budget_drops_capped_provider_then_blocks(db):
    o = org(db)
    manage.upsert_budget(db, o.id, "deepl", Decimal("1.00"), True)
    manage.create_route(db, o.id, {"engines": ["deepl", "google"], "fallback": False})
    assert choose(db, o).engines == ["deepl", "google"]
    budgets.charge(db, o.id, "deepl", Decimal("0.60"))
    budgets.charge(db, o.id, "deepl", Decimal("0.40"))
    assert budgets.get(db, o.id, "deepl").spent == Decimal("1.000000")
    c = choose(db, o)
    assert c.engines == ["google"] and c.skipped["deepl"] == "budget"
    manage.upsert_budget(db, o.id, "google", Decimal("0"), True)
    with pytest.raises(BudgetExceeded, match="budget exceeded") as e:
        choose(db, o)
    assert e.value.providers == ["deepl", "google"]
    # raising the cap resumes
    manage.upsert_budget(db, o.id, "deepl", Decimal("5"), True)
    assert choose(db, o).engines == ["deepl"]


def test_budget_new_month_restarts_spend(db):
    o = org(db)
    b = manage.upsert_budget(db, o.id, "anthropic", Decimal("2"), True)
    b.period, b.spent = "2000-01", Decimal("50")
    db.flush()
    assert not budgets.exceeded(db, o.id, "anthropic")
    budgets.charge(db, o.id, "anthropic", Decimal("0.5"))
    db.refresh(b)
    assert b.period == budgets.current_period() and b.spent == Decimal("0.500000")


def test_budgeted_wrappers_check_before_and_charge_after(db):
    from arbiter.contracts import MtRequest
    from arbiter.engines.budgets import BudgetedLlm, BudgetedMt
    from arbiter.engines.mock import MockLlm, MockMt

    o = org(db)
    manage.upsert_budget(db, o.id, "deepl", Decimal("0.001"), True)

    class PricedMt(MockMt):
        name = "deepl"

        def translate(self, requests):
            out = super().translate(requests)
            for r in out:
                r.usage.cost = Decimal("0.002")
            return out

    mt = BudgetedMt(PricedMt(name="deepl"), db, o.id, "deepl")
    mt.translate([MtRequest("Hello", "en", "de")])
    with pytest.raises(BudgetExceeded):
        mt.translate([MtRequest("Hello", "en", "de")])
    llm = BudgetedLlm(MockLlm(), db, o.id, "mock")
    assert llm.region == "local"
