from __future__ import annotations

import json

from quality_helpers import ctx, err, term

from arbiter.contracts import EngineError, MtRequest, QaIssue, TermViolation
from arbiter.engines.mock import MockLlm, MockMt, ScriptedLlm
from arbiter.quality.senate import build_role_prompt, review_senate, translation_senate, triage

SRC = "Zebra quantum invoice must be paid within thirty days of receipt by the customer"
TGT = "Faktura mora biti placena u roku od trideset dana od prijema od strane kupca"
CLEAN = {"errors": []}


def scripted(**per_role):
    """One ScriptedLlm answering per role; roles not given answer clean."""
    script = {r: [per_role.get(r, CLEAN)] for r in ("accuracy", "fluency", "terminology", "consistency")}
    if "verify" in per_role:
        script["verify"] = per_role["verify"]
    return ScriptedLlm(script)


def test_two_roles_overlap_confirmed_with_upper_median():
    llm = scripted(
        accuracy={"errors": [err("accuracy", "major", "trideset dana")]},
        terminology={"errors": [err("terminology", "critical", "dana")]},  # overlaps, compatible dim
    )
    v = review_senate(ctx(SRC, TGT), llm)
    assert v.outcome == "errors_confirmed" and v.roles_answered == 4
    [c] = v.confirmed
    assert c.severity == "critical"  # upper median of (major, critical)
    assert c.role == "accuracy+terminology"
    assert llm.calls_for("verify") == []


def test_three_roles_median_severity():
    llm = scripted(
        accuracy={"errors": [err("accuracy", "critical", "placena")]},
        terminology={"errors": [err("accuracy", "minor", "placena")]},
        consistency={"errors": [err("accuracy", "major", "biti placena")]},
    )
    [c] = review_senate(ctx(SRC, TGT), llm).confirmed
    assert c.severity == "major"


def test_incompatible_dimensions_do_not_merge():
    llm = scripted(
        accuracy={"errors": [err("accuracy", "major", "placena")]},
        fluency={"errors": [err("style", "major", "placena")]},
        verify=[{"improves": False}, {"improves": False}],
    )
    v = review_senate(ctx(SRC, TGT), llm)
    assert v.confirmed == [] and len(v.discarded) == 2 and len(llm.calls_for("verify")) == 2


def test_lone_finding_verified_yes_and_no():
    yes = scripted(accuracy={"errors": [err("accuracy", "major", "kupca")]}, verify=[{"improves": True}])
    v = review_senate(ctx(SRC, TGT), yes)
    assert [c.span for c in v.confirmed] == ["kupca"] and v.score is not None and v.score < 100
    verify_payload = yes.calls_for("verify")[0]["payload"]
    assert verify_payload["span"] == "kupca" and verify_payload["source"] == SRC

    no = scripted(accuracy={"errors": [err("accuracy", "major", "kupca")]}, verify=[{"improves": False}])
    v2 = review_senate(ctx(SRC, TGT), no)
    assert v2.confirmed == [] and [d.span for d in v2.discarded] == ["kupca"]
    assert v2.outcome == "clean" and v2.score == 100.0


def test_lone_minor_style_discarded_without_verification():
    llm = scripted(fluency={"errors": [err("style", "minor", "od strane kupca")]})
    v = review_senate(ctx(SRC, TGT), llm)
    assert v.confirmed == [] and len(v.discarded) == 1 and llm.calls_for("verify") == []


def test_verifier_failure_keeps_finding():
    llm = scripted(accuracy={"errors": [err("accuracy", "major", "kupca")]}, verify=[EngineError("down")])
    assert len(review_senate(ctx(SRC, TGT), llm).confirmed) == 1


def test_hallucinated_span_dropped_before_arbitration():
    llm = scripted(
        accuracy={"errors": [err("accuracy", "major", "not in target")]},
        terminology={"errors": [err("accuracy", "major", "not in target")]},
    )
    assert review_senate(ctx(SRC, TGT), llm).confirmed == []


def test_fluency_never_receives_source():
    c = ctx(SRC, TGT, context_before="Zebra context sentence.", context_after="After zebra.")
    system, user = build_role_prompt("fluency", c)
    assert "Zebra" not in user and "zebra" not in user and "source" not in json.loads(user)
    llm = scripted()
    review_senate(c, llm)
    [call] = llm.calls_for("fluency")
    assert "Zebra" not in call["user"] and "quantum" not in call["user"]
    # the other roles do see it
    assert "Zebra" in llm.calls_for("accuracy")[0]["user"]


def test_role_specific_inputs():
    c = ctx(
        SRC,
        TGT,
        terms=[term("mandatory", "invoice", "faktura")],
        style_rules=["Use Latin script"],
        document_targets=[("Invoice due", "Faktura dospeva")],
    )
    term_payload = json.loads(build_role_prompt("terminology", c)[1])
    assert term_payload["terms"][0]["kind"] == "mandatory" and term_payload["style_rules"] == [
        "Use Latin script"
    ]
    cons_payload = json.loads(build_role_prompt("consistency", c)[1])
    assert cons_payload["document"] == [{"source": "Invoice due", "target": "Faktura dospeva"}]


def test_void_when_roles_fail():
    llm = ScriptedLlm(
        {
            "accuracy": [CLEAN],
            "fluency": [EngineError("timeout")],
            "terminology": [EngineError("overloaded")],
            "consistency": [CLEAN],
        }
    )
    v = review_senate(ctx(SRC, TGT), llm)
    assert v.outcome == "void" and v.score is None and v.roles_answered == 2 and v.roles_total == 4
    assert {f["role"] for f in v.findings["_failed"]} == {"fluency", "terminology"}


def test_separate_clients_per_role():
    strong = scripted(accuracy={"errors": [err("accuracy", "major", "kupca")]}, verify=[{"improves": True}])
    cheap = MockLlm()
    v = review_senate(ctx(SRC, TGT), {"accuracy": strong, "default": cheap})
    assert len(v.confirmed) == 1
    assert {c["key"] for c in strong.calls} == {"accuracy", "verify"}


def test_mock_llm_end_to_end_markers():
    tgt = "Faktura {{mistranslation}} je {{style}} placena {{spurious}} odmah {{terminology}} ."
    v = review_senate(ctx("Invoice is paid immediately now in full by the client today.", tgt), MockLlm())
    spans = {c.span: c for c in v.confirmed}
    assert set(spans) == {"{{mistranslation}}", "{{terminology}}"}
    assert {d.span for d in v.discarded} == {"{{style}}", "{{spurious}}"}
    assert v.outcome == "errors_confirmed"


# ----------------------------------------------------------------- translation senate


def faktura_checker(target: str) -> list[TermViolation]:
    if "faktura" in target:
        return []
    return [TermViolation("t1", "mandatory", "term_missing", "error", "invoice -> faktura")]


REQ = MtRequest("Pay the invoice today.", "en", "sr", terms=[term("mandatory", "invoice", "faktura")])


def test_translation_senate_prefers_term_adherent_candidate():
    # The judge would love the non-adherent candidate and dislikes the adherent one,
    # but glossary adherence is checked first.
    def judge_fn(payload, _s, _u):
        if "faktura" in payload["target"]:
            return {"errors": [err("style", "major", "faktura")]}
        return CLEAN

    judge_llm = ScriptedLlm(default=judge_fn)
    engines = [MockMt("mt-a", faults={"omit_term"}), MockMt("mt-b")]
    v = translation_senate(REQ, engines, judge_llm, faktura_checker)
    assert v.outcome == "winner:mt-b" and "faktura" in (v.winner_target or "")
    assert v.score is not None and v.score < 100
    cands = {c["engine"]: c for c in v.findings["candidates"]}
    assert cands["mt-a"]["eliminated"] and "term_missing" in cands["mt-a"]["hard"]
    # the eliminated candidate is never judged
    assert all("faktura" in c["payload"]["target"] for c in judge_llm.calls)


def test_translation_senate_best_score_and_tie_by_order():
    judge_llm = ScriptedLlm(default=CLEAN)
    v = translation_senate(REQ, [MockMt("first"), MockMt("second")], judge_llm, faktura_checker)
    assert v.outcome == "winner:first"

    def judge_fn(payload, _s, _u):
        return (
            CLEAN
            if payload["target"].startswith("Páy")
            else {"errors": [err("accuracy", "major", "faktura")]}
        )

    class Upper(MockMt):
        def translate(self, requests):
            res = super().translate(requests)
            for r in res:
                r.target_tagged = r.target_tagged.replace("Páy", "PÁY")
            return res

    v2 = translation_senate(
        REQ, [Upper("upper"), MockMt("plain")], ScriptedLlm(default=judge_fn), faktura_checker
    )
    assert v2.outcome == "winner:plain" and v2.score == 100.0


def test_translation_senate_void_when_all_fail():
    engines = [MockMt("a", faults={"omit_term"}), MockMt("b", faults={"fail"})]
    v = translation_senate(REQ, engines, MockLlm(), faktura_checker)
    assert v.outcome == "void" and v.winner_target is None


def test_translation_senate_multiple_judges_averaged():
    j1 = ScriptedLlm(default=CLEAN)
    j2 = ScriptedLlm(default={"errors": [err("accuracy", "major", "faktura")]})
    v = translation_senate(REQ, [MockMt("only")], [j1, j2], faktura_checker)
    # 4 source words: one major -> 0 for judge 2; mean of 100 and 0
    assert v.score == 50.0


# ----------------------------------------------------------------- triage


def test_triage_never_clears_blocking():
    issues = [
        QaIssue("number_mismatch", "error", "3 vs 4", True),
        QaIssue("repeated_word", "warning", "the the", False),
        QaIssue("punctuation_end", "warning", "x", False),
    ]
    llm = ScriptedLlm(
        {
            "triage": [
                {
                    "labels": [
                        {"id": 0, "label": "false_positive", "reason": "trust me"},
                        {"id": 1, "label": "false_positive", "reason": "intentional"},
                    ]
                }
            ]
        }
    )
    out = triage(ctx(SRC, TGT), issues, llm)
    assert out[0]["label"] == "real" and out[0]["by"] == "rule"
    assert out[1]["label"] == "false_positive"
    assert out[2]["label"] == "real"  # missing label -> fail safe
    sent = llm.calls[0]["payload"]["warnings"]
    assert [w["id"] for w in sent] == [1, 2]  # blocking issue never shown to the model


def test_triage_model_failure_keeps_real():
    out = triage(ctx(SRC, TGT), [QaIssue("repeated_word", "warning", "x", False)], ScriptedLlm())
    assert out[0]["label"] == "real"
    out2 = triage(ctx(SRC, TGT), [QaIssue("repeated_word", "warning", "x", False)], MockLlm())
    assert out2[0]["label"] == "false_positive"
