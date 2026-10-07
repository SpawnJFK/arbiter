from __future__ import annotations

import json

import pytest
from quality_helpers import ctx, err, term

from arbiter.contracts import EngineError, MqmError, TermViolation
from arbiter.engines.mock import MockLlm, ScriptedLlm
from arbiter.quality.judge import build_judge_prompt, judge, parse_errors
from arbiter.quality.mqm import evaluation_word_count, mqm_score
from arbiter.quality.prompts import PROMPT_VERSION
from arbiter.quality.qe import score_segment

TWENTY = " ".join(f"w{i}" for i in range(20))


def e(sev: str) -> MqmError:
    return MqmError("accuracy", sev, "x", "y")  # type: ignore[arg-type]


# ----------------------------------------------------------------- MQM formula


@pytest.mark.parametrize(
    ("errors", "words", "expected"),
    [
        ([], 20, 100.0),
        ([e("minor")], 20, 95.0),
        ([e("major")], 20, 75.0),
        ([e("minor"), e("minor")], 20, 90.0),
        ([e("critical")], 20, 0.0),
        ([e("neutral")], 20, 100.0),
        ([e("major")], 100, 95.0),
        ([e("minor")], 0, 0.0),  # EWC floor 1 -> 100 - 100 = 0
    ],
)
def test_mqm_formula(errors, words, expected):
    assert mqm_score(errors, words) == expected


def test_word_count_cjk_and_floor():
    assert evaluation_word_count("one two three") == 3
    assert evaluation_word_count("") == 1
    assert evaluation_word_count("这是一个测试", "zh") == 3


# ----------------------------------------------------------------- judge


def test_judge_prompt_rewards_no_errors_and_is_json():
    system, user = build_judge_prompt(ctx("Open ⟦1⟧file⟦/1⟧", "Otvori ⟦1⟧datoteku⟦/1⟧"))
    assert "No errors" in system and '{"errors":[]}' in system
    data = json.loads(user)
    assert data["task"] == "judge" and data["prompt_version"] == PROMPT_VERSION
    assert data["target"] == "Otvori datoteku"  # codes removed


def test_judge_with_mock_llm_markers():
    src = f"{TWENTY} {{{{mistranslation}}}}"
    tgt = f"{TWENTY} {{{{mistranslation}}}}"
    qe = judge(ctx(src, tgt), MockLlm())
    assert [x.severity for x in qe.errors] == ["major"]
    assert qe.score == mqm_score(qe.errors, 21)
    assert PROMPT_VERSION in qe.model_version


def test_judge_clean_is_100():
    qe = score_segment(ctx("Open the file now please.", "Otvori datoteku sada molim."), MockLlm())
    assert qe.score == 100.0 and qe.errors == []


def test_blocking_hard_issue_zeroes_score_without_llm_call():
    llm = ScriptedLlm()  # would raise if called
    qe = judge(ctx("Click ⟦1/⟧ here", "Klikni ovde"), llm)
    assert qe.score == 0.0 and llm.calls == []
    assert any(i.blocking for i in qe.hard_issues)
    vio = [TermViolation("t", "mandatory", "term_missing", "error", "missing")]
    qe2 = judge(ctx("Open the invoice", "Otvori racun"), llm, vio)
    assert qe2.score == 0.0 and llm.calls == []


def test_judge_drops_hallucinated_spans_keeps_omissions_and_maps_dims():
    resp = {
        "errors": [
            err("accuracy", "major", "nije ovde"),  # hallucinated
            {
                "dimension": "Accuracy/Omission",
                "severity": "major",
                "span": "",
                "category": "omission",
                "explanation": "'now' omitted",
            },
            err("Fluency", "minor", "datoteku"),
            err("made_up", "major", "Otvori"),
            err("accuracy", "catastrophic", "Otvori"),
        ]
    }
    qe = judge(ctx("Open the file now.", "Otvori datoteku."), ScriptedLlm({"judge": [resp]}))
    assert [(x.dimension, x.severity, x.span) for x in qe.errors] == [
        ("accuracy", "major", ""),
        ("linguistic_conventions", "minor", "datoteku"),
    ]


def test_parse_errors_requires_list():
    with pytest.raises(EngineError):
        parse_errors({"nope": 1}, "x", role="judge")


def test_judge_engine_error_propagates():
    with pytest.raises(EngineError):
        judge(ctx("Open the file.", "Otvori datoteku."), ScriptedLlm({"judge": [EngineError("down")]}))


def test_judge_receives_terms():
    llm = ScriptedLlm({"judge": [{"errors": []}]})
    judge(ctx("Open invoice.", "Otvori fakturu.", terms=[term("mandatory", "invoice", "faktura")]), llm)
    assert llm.calls[0]["payload"]["terms"] == [
        {"source": "invoice", "target": "faktura", "kind": "mandatory"}
    ]
