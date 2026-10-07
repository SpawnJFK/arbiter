from __future__ import annotations

import json

import pytest

from arbiter.contracts import EngineError, MtRequest, TermHit
from arbiter.engines import tags
from arbiter.engines.llm_mt import LlmMt, build_translate_prompt
from arbiter.engines.mock import MockLlm, MockMt, ScriptedLlm, pseudo_translate, unpseudo
from arbiter.quality.prompts import payload

SRC = "Click ⟦1⟧Save⟦/1⟧ to store ⟦2/⟧ 3 files at https://ex.com/a, {0} left."


def test_mockmt_preserves_tags_numbers_urls_placeholders():
    [res] = MockMt().translate([MtRequest(SRC, "en", "sr")])
    assert res.error is None
    assert tags.token_list(res.target_tagged) == tags.token_list(SRC)
    assert "https://ex.com/a" in res.target_tagged
    assert "{0}" in res.target_tagged and " 3 " in res.target_tagged
    assert res.target_tagged != SRC
    assert unpseudo(res.target_tagged) == SRC
    assert res.usage.characters == len(tags.plain(SRC))


def test_mockmt_is_deterministic():
    req = MtRequest(SRC, "en", "de")
    assert MockMt().translate([req])[0].target_tagged == MockMt().translate([req])[0].target_tagged


def test_mockmt_keeps_escaped_brackets():
    src = "Use ⟦⟦x⟧⟧ literally ⟦1/⟧"
    out = MockMt().translate([MtRequest(src, "en", "sr")])[0].target_tagged
    assert "⟦⟦" in out and "⟧⟧" in out and "⟦1/⟧" in out


def test_mockmt_inserts_mandatory_terms_and_keeps_dnt():
    terms = [
        TermHit("t1", "mandatory", "invoice", "faktura", 0, 7),
        TermHit("t2", "do_not_translate", "Arbiter", None, 0, 0),
        TermHit("t3", "forbidden", "invoice", "racun", 0, 0),
    ]
    out = MockMt().translate([MtRequest("Send the invoice via Arbiter.", "en", "sr", terms=terms)])[0]
    assert "faktura" in out.target_tagged
    assert "Arbiter" in out.target_tagged
    assert "racun" not in out.target_tagged


@pytest.mark.parametrize(
    ("marker", "check"),
    [
        ("{{drop_tag}}", lambda out: "⟦1⟧" not in out and "⟦/1⟧" in out),
        ("{{wrong_number}}", lambda out: " 4 " in out),
        ("{{omit_term}}", lambda out: "faktura" not in out),
    ],
)
def test_mockmt_fault_markers(marker, check):
    terms = [TermHit("t1", "mandatory", "invoice", "faktura", 0, 0)]
    src = f"Open ⟦1⟧the invoice⟦/1⟧ in 3 days {marker}"
    out = MockMt().translate([MtRequest(src, "en", "sr", terms=terms)])[0].target_tagged
    assert marker not in out
    assert check(out)


def test_mockmt_fail_marker_and_engine_faults():
    assert MockMt().translate([MtRequest("x {{fail}}", "en", "sr")])[0].error
    bad = MockMt("mock-b", faults={"omit_term"})
    terms = [TermHit("t1", "mandatory", "invoice", "faktura", 0, 0)]
    assert (
        "faktura" not in bad.translate([MtRequest("the invoice", "en", "sr", terms=terms)])[0].target_tagged
    )


def test_mockllm_judge_flags_markers():
    llm = MockLlm()
    data, usage, model = llm.complete_json(
        "sys", payload("judge", source="a", target="b {{mistranslation}} c")
    )
    assert data["errors"][0]["dimension"] == "accuracy"
    assert data["errors"][0]["span"] == "{{mistranslation}}"
    assert usage.input_tokens > 0 and model == "mock-llm-1"
    clean, _, _ = llm.complete_json("sys", payload("judge", source="a", target="b"))
    assert clean == {"errors": []}


def test_mockllm_rejects_non_json_and_injected_failure():
    with pytest.raises(EngineError):
        MockLlm().complete_json("s", "not json")
    with pytest.raises(EngineError):
        MockLlm(fail_on={"fluency"}).complete_json("s", payload("senate_role", role="fluency", target="x"))


def test_scripted_llm_queues_per_role_and_records_calls():
    llm = ScriptedLlm({"accuracy": [{"errors": []}, EngineError("down")]}, default={"ok": True})
    assert llm.complete_json("s", payload("senate_role", role="accuracy"))[0] == {"errors": []}
    with pytest.raises(EngineError):
        llm.complete_json("s", payload("senate_role", role="accuracy"))
    assert llm.complete_json("s", payload("senate_role", role="accuracy"))[0] == {"ok": True}
    assert len(llm.calls_for("accuracy")) == 3
    no_default = ScriptedLlm()
    with pytest.raises(EngineError):
        no_default.complete_json("s", payload("judge"))


def test_llm_mt_prompt_contains_everything_and_translates():
    req = MtRequest(
        "Pay the ⟦1⟧invoice⟦/1⟧.",
        "en",
        "sr",
        terms=[TermHit("t1", "mandatory", "invoice", "faktura", 0, 0)],
        style_rules=["Use Latin script"],
        formality="formal",
        max_length=40,
        context_before="Previous.",
    )
    system, user = build_translate_prompt(req)
    data = json.loads(user)
    assert "⟦" in system  # instructs to keep tokens
    assert data["terms"][0] == {"source": "invoice", "target": "faktura", "kind": "mandatory", "note": ""}
    assert data["style_rules"] == ["Use Latin script"] and data["formality"] == "formal"
    assert data["max_length"] == 40 and data["context_before"] == "Previous."
    engine = LlmMt(MockLlm())
    assert engine.name == "llm-mt:mock-llm"
    [res] = engine.translate([req])
    assert "faktura" in res.target_tagged and tags.token_list(res.target_tagged) == ["⟦1⟧", "⟦/1⟧"]


def test_llm_mt_error_becomes_result_error():
    [res] = LlmMt(ScriptedLlm({"translate": [EngineError("boom")]})).translate([MtRequest("x", "en", "sr")])
    assert res.error and res.target_tagged == ""


def test_pseudo_translate_without_terms_accent_only():
    assert pseudo_translate("bad") == "bád"
