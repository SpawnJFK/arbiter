from __future__ import annotations

import pytest
from quality_helpers import ctx, term

from arbiter.contracts import EngineError, MqmError
from arbiter.engines.mock import MockLlm, ScriptedLlm
from arbiter.quality.calibration import detect_drift, escaped_rate, pick_control_sample, propose_threshold
from arbiter.quality.editor import apply_fixes

ERR = [MqmError("accuracy", "major", "crveni", "should be plavi", fix="plavi")]
SRC = "Click the ⟦1⟧blue⟦/1⟧ invoice button⟦2/⟧."
TGT = "Kliknite ⟦1⟧crveni⟦/1⟧ dugme za fakturu⟦2/⟧."
TERMS = [term("mandatory", "invoice", "fakturu")]


def editor_llm(target: str) -> ScriptedLlm:
    return ScriptedLlm({"edit": [{"target": target}]})


def test_editor_applies_valid_edit():
    new_target = "Kliknite ⟦1⟧plavi⟦/1⟧ dugme za fakturu⟦2/⟧."
    out, usage = apply_fixes(ctx(SRC, TGT, terms=TERMS), ERR, editor_llm(new_target))
    assert out == new_target and usage.input_tokens > 0


def test_editor_rejects_edit_that_drops_a_tag():
    out, _ = apply_fixes(ctx(SRC, TGT, terms=TERMS), ERR, editor_llm("Kliknite plavi dugme za fakturu⟦2/⟧."))
    assert out == TGT
    out2, _ = apply_fixes(
        ctx(SRC, TGT, terms=TERMS), ERR, editor_llm("Kliknite ⟦1⟧plavi⟦/1⟧ dugme za fakturu.")
    )
    assert out2 == TGT


def test_editor_rejects_lost_mandatory_term_and_new_blocking_issue():
    out, _ = apply_fixes(
        ctx(SRC, TGT, terms=TERMS), ERR, editor_llm("Kliknite ⟦1⟧plavi⟦/1⟧ dugme za racun⟦2/⟧.")
    )
    assert out == TGT
    src = "Pay 3 invoices ⟦1/⟧"
    tgt = "Platite 3 crvene fakture ⟦1/⟧"
    out2, _ = apply_fixes(ctx(src, tgt), ERR, editor_llm("Platite 4 fakture ⟦1/⟧"))
    assert out2 == tgt


def test_editor_with_mock_llm_and_drop_tag_marker():
    tgt = "Kliknite {{mistranslation}} ⟦1⟧plavi⟦/1⟧ dugme za fakturu⟦2/⟧."
    src = "Click {{mistranslation}} the ⟦1⟧blue⟦/1⟧ invoice button⟦2/⟧."
    out, _ = apply_fixes(ctx(src, tgt), ERR, MockLlm())
    # removing the marker would create a placeholder mismatch vs the source -> rejected
    assert out == tgt
    out2, _ = apply_fixes(ctx(SRC, "Kliknite ⟦1⟧plavi⟦/1⟧ {{edit_drop_tag}} dugme⟦2/⟧."), ERR, MockLlm())
    assert "⟦1⟧" in out2  # tag drop rejected


def test_editor_noop_failure_and_tier_guard():
    assert apply_fixes(ctx(SRC, TGT), [], ScriptedLlm())[0] == TGT
    assert apply_fixes(ctx(SRC, TGT), ERR, ScriptedLlm({"edit": [EngineError("x")]}))[0] == TGT
    with pytest.raises(ValueError):
        apply_fixes(ctx(SRC, TGT), ERR, MockLlm(), tier="hybrid")


# ----------------------------------------------------------------- calibration


def samples(n_good_high: int, escaped_at: list[float], low_scores: list[float]) -> list[tuple[float, bool]]:
    s = [(95.0, False)] * n_good_high
    s += [(x, True) for x in escaped_at]
    s += [(x, False) for x in low_scores]
    return s


def test_propose_threshold_lowers_within_step():
    # All errors escaped below 70: the ideal threshold is 70, but one call moves at most 3.
    data = samples(400, [65.0, 66.0], [72.0] * 100)
    new, reason = propose_threshold(78.0, data)
    assert new == 75.0 and "capped" in reason
    new2, _ = propose_threshold(78.0, data, max_step=10)
    assert new2 == 68.0 or new2 <= 70.0


def test_propose_threshold_raises_when_escapes_above():
    data = samples(300, [80.0, 81.0, 82.0], [60.0] * 50)
    new, _ = propose_threshold(78.0, data)
    assert 78.0 < new <= 81.0


def test_propose_threshold_bounds_and_min_samples():
    assert propose_threshold(78.0, [(90.0, False)] * 10) == (78.0, "kept: 10 samples < 200 required")
    # every sample escaped: no threshold works -> step up, never above 99
    new, _ = propose_threshold(98.0, [(99.5, True)] * 300)
    assert new == 99.0
    # very clean data cannot push the threshold below 60
    new_low, _ = propose_threshold(61.0, [(65.0, False)] * 300, max_step=10)
    assert new_low == 60.0
    # nothing would auto-approve at any threshold: nothing to learn, keep
    kept, reason = propose_threshold(78.0, [(10.0, False)] * 300)
    assert kept == 78.0 and "no auto-approvable" in reason


def test_escaped_rate():
    assert escaped_rate([(90, True), (90, False), (50, True)], 80) == (0.5, 2)
    assert escaped_rate([], 80) == (0.0, 0)


def test_detect_drift():
    assert not detect_drift(1.0, 1.2)
    assert detect_drift(1.0, 1.4)
    assert detect_drift(1.0, 0.6)  # a judge gone lax is drift too
    assert not detect_drift(0.0, 0.0)
    assert detect_drift(0.0, 0.1)


def test_pick_control_sample_deterministic_and_rate():
    picks = [pick_control_sample(f"seg-{i}", 0.02) for i in range(20000)]
    assert picks == [pick_control_sample(f"seg-{i}", 0.02) for i in range(20000)]
    assert 0.015 < sum(picks) / len(picks) < 0.025
    assert not pick_control_sample("x", 0) and pick_control_sample("x", 1)
