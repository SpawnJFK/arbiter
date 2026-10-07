from __future__ import annotations

from typing import Any

from arbiter.contracts import SegmentContext, TermHit


def ctx(source: str, target: str, src: str = "en", tgt: str = "sr", **kw: Any) -> SegmentContext:
    return SegmentContext(
        segment_id=kw.pop("segment_id", "seg-1"),
        source_tagged=source,
        target_tagged=target,
        source_lang=src,
        target_lang=tgt,
        **kw,
    )


def codes(issues) -> list[str]:
    return [i.code for i in issues]


def term(kind: str, source: str, target: str | None, tid: str = "t1") -> TermHit:
    return TermHit(tid, kind, source, target, 0, len(source))  # type: ignore[arg-type]


def err(dimension: str, severity: str, span: str, explanation: str = "x") -> dict[str, Any]:
    return {
        "dimension": dimension,
        "severity": severity,
        "span": span,
        "explanation": explanation,
        "fix": "y",
    }
