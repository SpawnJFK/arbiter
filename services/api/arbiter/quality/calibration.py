"""Threshold calibration, drift detection and control sampling (pure functions).

Why pure: calibration runs weekly from stored control-sample outcomes; keeping it free of
I/O makes every proposal reproducible from the same inputs and trivially testable. The
caller persists the new value and the reason in provenance.

* propose_threshold: the threshold should be the LOWEST value at which auto-approved
  segments still meet the escaped-error target (default 0.5%): lower means more
  automation, but never at the cost of quality. Movement is limited to max_step per call
  (settings.max_threshold_step_per_week) so one noisy week cannot swing routing, and the
  value is clamped to [60, 99]: below 60 the judge is not trustworthy enough to auto-approve
  anything, above 99 nothing would ever be automated.
* detect_drift: the judge's flag rate (errors per segment) moving by more than ratio
  (default 30%) in EITHER direction means the judge or the input distribution changed;
  a sudden drop is as suspicious as a rise (a judge gone lax). The caller suspends
  auto-approval for that threshold.
* pick_control_sample: deterministic hash so the same segment is always in or out of the
  control sample (re-runs and retries cannot cherry-pick).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

MIN_THRESHOLD = 60.0
MAX_THRESHOLD = 99.0
GRID_STEP = 0.5


def escaped_rate(samples: Sequence[tuple[float, bool]], threshold: float) -> tuple[float, int]:
    """Escaped-error rate among samples that would auto-approve at this threshold, and their count."""
    auto = [esc for score, esc in samples if score >= threshold]
    if not auto:
        return 0.0, 0
    return sum(1 for e in auto if e) / len(auto), len(auto)


def propose_threshold(
    current: float,
    samples: Sequence[tuple[float, bool]],
    target_escaped_rate: float = 0.005,
    max_step: float = 3.0,
    *,
    min_samples: int = 200,
) -> tuple[float, str]:
    """Return (new_threshold, reason). ``samples`` = (score, escaped) of human-checked
    control segments, escaped=True when the human found an error the system missed."""
    current = min(MAX_THRESHOLD, max(MIN_THRESHOLD, current))
    if len(samples) < min_samples:
        return current, f"kept: {len(samples)} samples < {min_samples} required"

    if escaped_rate(samples, MIN_THRESHOLD)[1] == 0:
        return current, f"kept: no auto-approvable samples at or above {MIN_THRESHOLD}"

    ideal: float | None = None
    t = MIN_THRESHOLD
    while t <= MAX_THRESHOLD + 1e-9:
        rate, n = escaped_rate(samples, t)
        if n > 0 and rate <= target_escaped_rate:
            ideal = t
            break
        t = round(t + GRID_STEP, 2)

    if ideal is None:
        new = min(MAX_THRESHOLD, current + max_step)
        reason = f"no threshold meets escaped rate {target_escaped_rate:.3%}; raised by up to {max_step}"
    else:
        delta = max(-max_step, min(max_step, ideal - current))
        new = current + delta
        rate, n = escaped_rate(samples, ideal)
        capped = " (step capped)" if abs(ideal - current) > max_step else ""
        reason = f"ideal {ideal:.1f}: escaped {rate:.3%} over {n} auto-approvable samples{capped}"
    new = round(min(MAX_THRESHOLD, max(MIN_THRESHOLD, new)), 1)
    if new == current:
        reason = "kept: " + reason
    return new, reason


def detect_drift(baseline_flags_per_segment: float, current: float, ratio: float = 0.30) -> bool:
    """True when the flag rate moved by more than ``ratio`` relative to baseline, either way.
    A zero baseline drifts as soon as anything is flagged."""
    if baseline_flags_per_segment <= 0:
        return current > 0
    return abs(current - baseline_flags_per_segment) / baseline_flags_per_segment > ratio


def pick_control_sample(segment_id: str, rate: float, *, salt: str = "control-v1") -> bool:
    """Deterministically pick ~rate of segments (SHA-256 of salt+id mapped to [0, 1))."""
    if rate <= 0:
        return False
    if rate >= 1:
        return True
    h = hashlib.sha256(f"{salt}:{segment_id}".encode()).digest()
    return int.from_bytes(h[:8], "big") / 2**64 < rate
