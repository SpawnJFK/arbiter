"""Provider clients against httpx.MockTransport: no network, fake keys only."""

from __future__ import annotations

import json

import httpx
import pytest

from arbiter.config import Settings
from arbiter.contracts import EngineError, MtRequest
from arbiter.engines import tags
from arbiter.engines.anthropic import AnthropicClient
from arbiter.engines.deepl import DeepLEngine, from_xml, to_xml
from arbiter.engines.google import GoogleEngine, from_html, to_html
from arbiter.engines.http import extract_json
from arbiter.engines.openai import OpenAiClient

S = Settings(env="test")
FAKE = "test-key-not-real"


def transport(responses: list[httpx.Response], seen: list[httpx.Request]) -> httpx.Client:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return queue.pop(0)

    return httpx.Client(transport=httpx.MockTransport(handler))


def anthropic_ok(text: str, model: str = "claude-opus-5-5") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "type": "message",
            "model": model,
            "content": [{"type": "text", "text": text}],
            "usage": {"input_tokens": 1000, "output_tokens": 200},
        },
    )


# ------------------------------------------------------------------ anthropic


def test_anthropic_parses_json_and_cost():
    seen: list[httpx.Request] = []
    client = AnthropicClient(S, api_key=FAKE, http_client=transport([anthropic_ok('{"errors": []}')], seen))
    data, usage, model = client.complete_json("sys", '{"task":"judge"}', schema_hint="{}")
    assert data == {"errors": []} and model == "claude-opus-5-5"
    assert usage.input_tokens == 1000 and usage.output_tokens == 200 and usage.cost > 0
    req = seen[0]
    assert req.headers["x-api-key"] == FAKE and req.headers["anthropic-version"] == "2023-06-01"
    body = json.loads(req.content)
    assert body["messages"][0] == {"role": "user", "content": '{"task":"judge"}'}
    assert "JSON" in body["system"] and body["model"] == "claude-opus-5-5"


def test_anthropic_retries_429_529_and_bad_json():
    seen: list[httpx.Request] = []
    responses = [
        httpx.Response(429, json={"type": "error"}),
        httpx.Response(529, json={"type": "error", "error": {"type": "overloaded_error"}}),
        anthropic_ok("Sure! Here you go: no json"),
        anthropic_ok('```json\n{"ok": 1}\n```'),
    ]
    client = AnthropicClient(S, api_key=FAKE, http_client=transport(responses, seen), attempts=5, backoff=0)
    data, usage, _ = client.complete_json("s", "u")
    assert data == {"ok": 1} and len(seen) == 4
    assert usage.input_tokens == 2000  # both answered attempts are billed


def test_anthropic_gives_up_and_does_not_retry_400():
    seen: list[httpx.Request] = []
    client = AnthropicClient(
        S, api_key=FAKE, http_client=transport([httpx.Response(500)] * 3, seen), attempts=3, backoff=0
    )
    with pytest.raises(EngineError):
        client.complete_json("s", "u")
    assert len(seen) == 3
    seen.clear()
    client = AnthropicClient(S, api_key=FAKE, http_client=transport([httpx.Response(400)], seen), backoff=0)
    with pytest.raises(EngineError):
        client.complete_json("s", "u")
    assert len(seen) == 1


def test_anthropic_without_key_raises_before_network():
    with pytest.raises(EngineError):
        AnthropicClient(S).complete_json("s", "u")


# ------------------------------------------------------------------ openai


def test_openai_json_mode():
    seen: list[httpx.Request] = []
    resp = httpx.Response(
        200,
        json={
            "model": "gpt-5-2026",
            "choices": [{"message": {"content": '{"translation": "x"}'}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 10},
        },
    )
    client = OpenAiClient(S, api_key=FAKE, http_client=transport([resp], seen))
    data, usage, model = client.complete_json("sys", "user")
    assert data == {"translation": "x"} and model == "gpt-5-2026" and usage.input_tokens == 50
    body = json.loads(seen[0].content)
    assert body["response_format"] == {"type": "json_object"}
    assert "temperature" not in body  # gpt-5 rejects custom temperature
    assert seen[0].headers["authorization"] == f"Bearer {FAKE}"


def test_openai_retries_503_then_ok():
    seen: list[httpx.Request] = []
    ok = httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}], "usage": {}})
    client = OpenAiClient(
        S, api_key=FAKE, model="gpt-4.1", http_client=transport([httpx.Response(503), ok], seen), backoff=0
    )
    assert client.complete_json("s", "u")[0] == {}
    assert json.loads(seen[1].content)["temperature"] == 0.0


def test_extract_json_variants():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('text {"a": 2} more') == {"a": 2}
    with pytest.raises(EngineError):
        extract_json("[1, 2]")


# ------------------------------------------------------------------ deepl


TAGGED = "Click ⟦1⟧Save & ⟦2⟧close⟦/2⟧⟦/1⟧ now⟦3/⟧ <b> ⟦⟦lit⟧⟧"


def test_deepl_xml_roundtrip():
    xml = to_xml(TAGGED)
    assert '<g id="1">' in xml and '<x id="3"/>' in xml and "&amp;" in xml and "&lt;b&gt;" in xml
    assert from_xml(xml) == TAGGED


def test_deepl_unbalanced_source_uses_selfclosing():
    xml = to_xml("a⟦1⟧b")
    assert '<bx id="1"/>' in xml
    assert from_xml(xml) == "a⟦1⟧b"


def test_deepl_translate_request_and_back_conversion():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        # pretend translation: uppercase text outside tags, keep tags
        return httpx.Response(
            200, json={"translations": [{"text": t.replace("Click", "Klik")} for t in body["text"]]}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    engine = DeepLEngine(S, api_key=FAKE + ":fx", http_client=client)
    reqs = [
        MtRequest(TAGGED, "en", "sr", formality="formal"),
        MtRequest("Click ⟦1/⟧", "en", "sr", formality="formal"),
    ]
    out = engine.translate(reqs)
    assert [r.error for r in out] == [None, None]
    assert out[0].target_tagged == TAGGED.replace("Click", "Klik")
    assert tags.token_list(out[1].target_tagged) == ["⟦1/⟧"]
    assert len(seen) == 1 and seen[0].url.host == "api-free.deepl.com"
    body = json.loads(seen[0].content)
    assert (
        body["tag_handling"] == "xml" and body["target_lang"] == "SR" and body["formality"] == "prefer_more"
    )
    assert seen[0].headers["authorization"] == f"DeepL-Auth-Key {FAKE}:fx"
    assert out[0].usage.characters == len(tags.plain(TAGGED)) and out[0].usage.cost > 0


def test_deepl_failure_becomes_result_error():
    seen: list[httpx.Request] = []
    engine = DeepLEngine(S, api_key=FAKE, http_client=transport([httpx.Response(403)], seen), backoff=0)
    [res] = engine.translate([MtRequest("x", "en", "de")])
    assert res.error and "403" in res.error and res.target_tagged == ""


# ------------------------------------------------------------------ google


def test_google_html_roundtrip():
    html_text = to_html(TAGGED)
    assert '<span id="a1">' in html_text and 'translate="no" id="s3"' in html_text
    assert from_html(html_text) == TAGGED
    assert from_html(to_html("a⟦1⟧b")) == "a⟦1⟧b"


def test_google_translate_uses_header_key_and_html():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        return httpx.Response(
            200, json={"data": {"translations": [{"translatedText": q} for q in body["q"]]}}
        )

    engine = GoogleEngine(S, api_key=FAKE, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    [res] = engine.translate([MtRequest(TAGGED, "en", "sr")])
    assert res.error is None and res.target_tagged == TAGGED
    assert seen[0].headers["x-goog-api-key"] == FAKE and FAKE not in str(seen[0].url)
    assert json.loads(seen[0].content)["format"] == "html"
