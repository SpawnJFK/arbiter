"""Segments back to file units, honouring editor splits and merges.

A format handler merges a target map whose units have exactly the segment count of the
extraction. The workbench can split and merge segments inside a unit, so the database
may hold a different count. Each segment carries `signals["slots"]`, the number of
extraction slots it covers:

    1   (default) a segment as extracted
    k   a merge of k extracted segments: its target goes into the first slot, the other
        k-1 slots are written empty (the merged translation covers them)
    0   the second half of a split: its target is appended to the previous slot

so concatenating slots always gives back the extraction count. Splits keep the exact
source text on both sides (no characters are lost), merges join the sources with the
inter-segment whitespace of the original unit.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from arbiter.fileproc.base import Content, InlineCode, from_tagged


def slots_of(seg: Any) -> int:
    value = (getattr(seg, "signals", None) or {}).get("slots", 1)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 1


def codes_of_segment(seg: Any) -> list[InlineCode]:
    return [InlineCode(**c) for c in (seg.source_codes or [])]


def content_of(seg: Any, *, use_source_when_empty: bool = True) -> Content | None:
    """Target content of a segment (source when there is no usable target, if allowed)."""
    codes = codes_of_segment(seg)
    if seg.target_tagged:
        try:
            return from_tagged(seg.target_tagged, codes)
        except ValueError:
            pass
    if not use_source_when_empty:
        return None
    return from_tagged(seg.source_tagged, codes)


def _join(a: Content, b: Content) -> Content:
    out: Content = list(a)
    for r in b:
        if isinstance(r, str) and out and isinstance(out[-1], str):
            out[-1] = out[-1] + r
        else:
            out.append(r)
    return out


def regroup(
    segments: Iterable[Any],
    content: Callable[[Any], Content | None] | None = None,
) -> dict[str, list[Content | None]]:
    """unit_id -> slot contents in extraction order. `segments` may come in any order."""
    pick = content or (lambda s: content_of(s))
    by_unit: dict[str, list[Any]] = {}
    for seg in segments:
        by_unit.setdefault(seg.unit_id, []).append(seg)
    out: dict[str, list[Content | None]] = {}
    for unit_id, segs in by_unit.items():
        slots: list[Content | None] = []
        for seg in sorted(segs, key=lambda s: s.seg_index):
            c = pick(seg)
            n = slots_of(seg)
            if n == 0 and slots:
                prev = slots[-1]
                slots[-1] = None if prev is None or c is None else _join(prev, c)
                continue
            slots.append(c)
            slots.extend([[] for _ in range(max(0, n - 1))])
        out[unit_id] = slots
    return out


def target_map(segments: Iterable[Any]) -> dict[str, list[Content]]:
    """Full target map for merge(): untranslated segments fall back to their source."""
    return {u: [c or [] for c in slots] for u, slots in regroup(segments).items()}
