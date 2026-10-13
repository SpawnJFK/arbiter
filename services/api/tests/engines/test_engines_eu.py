"""EU route engines (D-057) and the OpenAI-compatible client, with stubbed transports only."""

from __future__ import annotations

import json
from decimal import Decimal

import boto3
import httpx
import jwt
import pytest
from botocore.stub import Stubber
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from arbiter.contracts import EngineError, MtRequest
from arbiter.engines import bedrock, vertex
from arbiter.engines.bedrock import BedrockClient
from arbiter.engines.openai_compatible import (
    CustomModelMt,
    OpenAiCompatibleClient,
    from_training_text,
    to_training_text,
)
from arbiter.engines.pricing import estimate_cost
from arbiter.engines.vertex import VertexClient

# ------------------------------------------------------------------ Bedrock


def _bedrock_client():
    return boto3.client(
        "bedrock-runtime",
        region_name="eu-central-1",
        aws_access_key_id="AKIDEXAMPLE",
        aws_secret_access_key="secret-example",
    )


def _converse_reply(text: str, inp: int = 120, out: int = 30) -> dict:
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": inp, "outputTokens": out, "totalTokens": inp + out},
        "metrics": {"latencyMs": 12},
    }


def test_bedrock_region_from_inference_profile():
    assert bedrock.processing_region("eu.anthropic.claude-opus-5", "eu-central-1") == "eu"
    assert bedrock.processing_region("eu.anthropic.claude-opus-5", "us-east-1") == "eu"
    assert bedrock.processing_region("global.anthropic.claude-opus-5", "eu-central-1") == "global"
    assert bedrock.processing_region("us.anthropic.claude-opus-5", "us-east-1") == "us"
    assert bedrock.processing_region("anthropic.claude-opus-5", "eu-west-1") == "eu"
    assert bedrock.processing_region("anthropic.claude-opus-5", "ap-south-1") == "global"


def test_bedrock_converse_json_usage_cost_and_params():
    client = _bedrock_client()
    stub = Stubber(client)
    stub.add_response(
        "converse",
        _converse_reply('Sure: ```json\n{"translation": "Zdravo"}\n```'),
        expected_params={
            "modelId": "eu.anthropic.claude-opus-5",
            "system": [{"text": stub_any_text()}],
            "messages": [{"role": "user", "content": [{"text": "hello"}]}],
            "inferenceConfig": {"maxTokens": 50, "temperature": 0.0},
        },
    )
    with stub:
        llm = BedrockClient(model="eu.anthropic.claude-opus-5", aws_region="eu-central-1", client=client)
        assert llm.region == "eu" and llm.available()
        data, usage, model = llm.complete_json("sys", "hello", max_tokens=50)
    assert data == {"translation": "Zdravo"}
    assert (usage.input_tokens, usage.output_tokens) == (120, 30)
    assert usage.cost == estimate_cost(
        "bedrock", model="eu.anthropic.claude-opus-5", input_tokens=120, output_tokens=30
    )
    assert usage.cost > 0 and isinstance(usage.cost, Decimal)
    assert model == "bedrock:eu.anthropic.claude-opus-5"


def stub_any_text():
    from botocore.stub import ANY

    return ANY


def test_bedrock_retries_throttling_then_succeeds_and_bills_both_attempts():
    client = _bedrock_client()
    stub = Stubber(client)
    stub.add_client_error("converse", service_error_code="ThrottlingException", http_status_code=429)
    stub.add_response("converse", _converse_reply("not json at all", 10, 5))
    stub.add_response("converse", _converse_reply('{"ok": true}', 10, 5))
    with stub:
        llm = BedrockClient(
            model="eu.anthropic.claude-opus-5", aws_region="eu-central-1", client=client, backoff=0
        )
        data, usage, _ = llm.complete_json("s", "u")
    assert data == {"ok": True}
    assert usage.input_tokens == 20  # the bad-JSON attempt reached the model and is billed
    stub.assert_no_pending_responses()


def test_bedrock_access_denied_is_not_retried():
    client = _bedrock_client()
    stub = Stubber(client)
    stub.add_client_error("converse", service_error_code="AccessDeniedException", http_status_code=403)
    with stub, pytest.raises(EngineError, match="AccessDeniedException"):
        BedrockClient(
            model="eu.anthropic.claude-opus-5", aws_region="eu-central-1", client=client, backoff=0
        ).complete_json("s", "u")


def test_bedrock_without_credentials_is_unavailable():
    llm = BedrockClient(model="eu.anthropic.claude-opus-5", aws_region="eu-central-1")
    assert not llm.available()
    with pytest.raises(EngineError):
        llm.complete_json("s", "u")


# ------------------------------------------------------------------ Vertex


@pytest.fixture(scope="module")
def service_account() -> tuple[dict, object]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    sa = {
        "type": "service_account",
        "project_id": "proj-eu",
        "private_key_id": "kid123",
        "private_key": pem,
        "client_email": "arbiter@proj-eu.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    return sa, key.public_key()


def test_vertex_hosts_and_regions():
    assert vertex.host_for("eu") == "aiplatform.eu.rep.googleapis.com"
    assert vertex.host_for("global") == "aiplatform.googleapis.com"
    assert vertex.host_for("europe-west4") == "europe-west4-aiplatform.googleapis.com"
    assert vertex.processing_region("eu") == "eu"
    assert vertex.processing_region("europe-west1") == "eu"
    assert vertex.processing_region("us-east5") == "us"
    assert vertex.processing_region("global") == "global"


def test_vertex_jwt_exchange_then_raw_predict(service_account):
    sa, public_key = service_account
    calls: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if req.url.host == "oauth2.googleapis.com":
            form = dict(x.split("=", 1) for x in req.content.decode().split("&"))
            assert form["grant_type"] == "urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer"
            claims = jwt.decode(form["assertion"], public_key, algorithms=["RS256"], audience=sa["token_uri"])
            assert claims["iss"] == sa["client_email"]
            assert claims["scope"] == vertex.SCOPE
            assert jwt.get_unverified_header(form["assertion"])["kid"] == "kid123"
            return httpx.Response(200, json={"access_token": "ya29.token", "expires_in": 3600})
        assert req.url.host == "aiplatform.eu.rep.googleapis.com"
        assert req.url.path == (
            "/v1/projects/proj-eu/locations/eu/publishers/anthropic/models/claude-opus-5:rawPredict"
        )
        assert req.headers["authorization"] == "Bearer ya29.token"
        body = json.loads(req.content)
        assert body["anthropic_version"] == vertex.VERTEX_VERSION
        assert "model" not in body
        return httpx.Response(
            200,
            json={
                "model": "claude-opus-5",
                "content": [{"type": "text", "text": '{"score": 1}'}],
                "usage": {"input_tokens": 100, "output_tokens": 10},
            },
        )

    llm = VertexClient(
        service_account=json.dumps(sa),
        model="claude-opus-5",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        backoff=0,
    )
    assert llm.region == "eu" and llm.project == "proj-eu" and llm.available()
    data, usage, model = llm.complete_json("sys", "user")
    data2, _, _ = llm.complete_json("sys", "user")
    assert data == data2 == {"score": 1}
    assert usage.input_tokens == 100 and usage.cost > 0
    assert model == "vertex:claude-opus-5"
    # the token is cached: one exchange, two predictions
    assert [c.url.host for c in calls].count("oauth2.googleapis.com") == 1


def test_vertex_401_refreshes_token_and_retries(service_account):
    sa, _ = service_account
    state = {"tokens": 0, "predict": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "oauth2.googleapis.com":
            state["tokens"] += 1
            return httpx.Response(200, json={"access_token": f"t{state['tokens']}", "expires_in": 3600})
        state["predict"] += 1
        if state["predict"] == 1:
            return httpx.Response(429, json={"error": "rate"})
        return httpx.Response(200, json={"content": [{"type": "text", "text": "{}"}], "usage": {}})

    llm = VertexClient(
        service_account=sa,
        model="claude-opus-5",
        location="europe-west4",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        backoff=0,
    )
    assert llm.url.startswith("https://europe-west4-aiplatform.googleapis.com/")
    assert llm.complete_json("s", "u")[0] == {}
    assert state["predict"] == 2


def test_vertex_incomplete_account_unavailable():
    assert not VertexClient(service_account="", model="m").available()


# ------------------------------------------------------------------ OpenAI-compatible + custom models


def test_openai_compatible_client_json_and_config_prices():
    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["auth"] = req.headers.get("authorization")
        seen["body"] = json.loads(req.content)
        return httpx.Response(
            200,
            json={
                "model": "mistral-large",
                "choices": [{"message": {"content": '{"translation": "Zdravo"}'}}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 1000},
            },
        )

    client = OpenAiCompatibleClient.from_config(
        "compat:ecr_1",
        "sk-x",
        {
            "endpoint": "https://eu.example.com/v1/",
            "model": "mistral-large",
            "region": "eu",
            "price_in_per_m": "2",
            "price_out_per_m": "6",
        },
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        backoff=0,
    )
    assert client.region == "eu"
    data, usage, model = client.complete_json("sys", "u")
    assert data == {"translation": "Zdravo"}
    assert seen["url"] == "https://eu.example.com/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-x"
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert usage.cost == Decimal("0.008000")  # 1000 * 2/1M + 1000 * 6/1M


def test_openai_compatible_unknown_region_is_global_and_missing_model_unavailable():
    c = OpenAiCompatibleClient(name="compat:x", base_url="https://h/v1", api_key="", model="", region="mars")
    assert c.region == "global" and not c.available()


def test_training_text_roundtrip_keeps_tags_and_escapes():
    tagged = "Open ⟦1⟧Settings⟦/1⟧ ⟦2/⟧ & use a < b, ⟦⟦literal⟧⟧"
    text = to_training_text(tagged)
    assert text == "Open <g1>Settings</g1> <x2/> &amp; use a &lt; b, ⟦literal⟧"
    assert from_training_text(text) == tagged


def test_custom_model_mt_speaks_training_format():
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert "response_format" not in body
        assert body["messages"][1]["content"] == "Open <g1>file</g1>"
        assert "en" in body["messages"][0]["content"] and "sr" in body["messages"][0]["content"]
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "Otvori <g1>datoteku</g1>"}}], "usage": {}}
        )

    client = OpenAiCompatibleClient(
        name="custom:cmd_1",
        base_url="https://ft.example.com/v1",
        api_key="k",
        model="acct/ft-1",
        json_mode=False,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        backoff=0,
    )
    mt = CustomModelMt(client, name="custom:cmd_1")
    res = mt.translate([MtRequest("Open ⟦1⟧file⟦/1⟧", "en", "sr")])[0]
    assert res.error is None and res.target_tagged == "Otvori ⟦1⟧datoteku⟦/1⟧"
    assert res.engine == "custom:cmd_1"


def test_custom_model_mt_reports_errors_per_segment():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    client = OpenAiCompatibleClient(
        name="custom:cmd_2",
        base_url="https://ft.example.com/v1",
        api_key="k",
        model="m",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        backoff=0,
    )
    res = CustomModelMt(client, name="custom:cmd_2").translate([MtRequest("a", "en", "sr")])[0]
    assert res.error and "401" in res.error
