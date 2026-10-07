"""decide(): exhaustive tier x regulated x suspended x score zone (R-SEG-12 for regulated)."""

from __future__ import annotations

import itertools

import pytest

from arbiter.contracts import QaIssue
from arbiter.quality.qe import TIERS, decide

T, B = 78.0, 8.0
ZONES = {
    "high": 90.0,
    "high_edge": 86.0,
    "band_hi": 80.0,
    "band_hi_edge": 78.0,
    "band_lo": 74.0,
    "low_edge": 70.0,
    "low": 50.0,
}
ZONE_CLASS = {
    "high": "high",
    "high_edge": "high",
    "band_hi": "band_hi",
    "band_hi_edge": "band_hi",
    "band_lo": "band_lo",
    "low_edge": "low",
    "low": "low",
}
A, S, R = "auto_approve", "senate", "review"
EXPECTED = {
    ("auto", False): {"high": A, "band_hi": S, "band_lo": S, "low": R},
    ("auto", True): {"high": S, "band_hi": S, "band_lo": S, "low": R},
    ("ai_review", False): {"high": A, "band_hi": S, "band_lo": S, "low": S},
    ("ai_review", True): {"high": S, "band_hi": S, "band_lo": S, "low": S},
    ("hybrid", False): {"high": A, "band_hi": S, "band_lo": R, "low": R},
    ("hybrid", True): {"high": R, "band_hi": R, "band_lo": R, "low": R},
    ("full", False): {"high": R, "band_hi": R, "band_lo": R, "low": R},
    ("full", True): {"high": R, "band_hi": R, "band_lo": R, "low": R},
}
BLOCK = QaIssue("tag_missing", "error", "x", True)
WARN = QaIssue("repeated_word", "warning", "x", False)


@pytest.mark.parametrize(
    ("tier", "regulated", "suspended", "zone"),
    list(itertools.product(TIERS, (False, True), (False, True), ZONES)),
)
def test_decision_table(tier, regulated, suspended, zone):
    score = ZONES[zone]
    got = decide(score, [WARN], T, B, tier=tier, regulated=regulated, suspended=suspended)
    expected = R if regulated else EXPECTED[(tier, suspended)][ZONE_CLASS[zone]]
    assert got == expected
    # a blocking hard issue wins over everything
    assert decide(score, [BLOCK], T, B, tier=tier, regulated=regulated, suspended=suspended) == "blocked"
    # never auto-approve when regulated or suspended
    if regulated or suspended:
        assert got != "auto_approve"


def test_safety_offset_shifts_zones():
    assert decide(87, [], T, B, tier="auto", regulated=False) == A
    assert decide(87, [], T, B, tier="auto", regulated=False, safety_offset=2) == S
    assert decide(71, [], T, B, tier="auto", regulated=False, safety_offset=2) == R
    # a negative offset can never lower the bar
    assert decide(85, [], T, B, tier="auto", regulated=False, safety_offset=-5) == S


def test_missing_score_never_auto():
    assert decide(None, [], T, B, tier="auto", regulated=False) == R
    assert decide(None, [], T, B, tier="ai_review", regulated=False) == S


def test_unknown_tier_rejected():
    with pytest.raises(ValueError):
        decide(90, [], T, B, tier="gold", regulated=False)
