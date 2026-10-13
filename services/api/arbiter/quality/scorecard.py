"""MQM scorecards (LQA): counts by dimension and severity, penalty, score, pass or fail.

Shared by the job LQA (module ai) and the standalone auditor (module auditor), so both
use one formula and one export layout.

Formula (document level, the same linear model as quality/mqm.py, per 100 words):

    penalty = sum(SEVERITY_WEIGHT[severity] * weight[dimension])   neutral 0, minor 1, major 5, critical 25
    score   = 100 - penalty * 100 / evaluation_words, clamped to [0, 100]
    passed  = score >= threshold

Org settings (org.settings["lqa"]): {"threshold": 95.0, "weights": {dimension: factor}}.
A weight of 0 ignores a dimension, 2 doubles it. Unknown dimensions count as "other"
with weight 1. The default threshold 95 means one major error per 100 words fails.
"""

from __future__ import annotations

import io
from collections.abc import Iterable
from typing import Any

from arbiter.contracts import MQM_DIMENSIONS, SEVERITY_WEIGHT
from arbiter.quality.judge import _norm_dimension

SEVERITIES = ("neutral", "minor", "major", "critical")
DIMENSIONS = (*MQM_DIMENSIONS, "other")
DEFAULT_THRESHOLD = 95.0


def default_settings() -> dict[str, Any]:
    return {"threshold": DEFAULT_THRESHOLD, "weights": dict.fromkeys(DIMENSIONS, 1.0)}


def settings_for(org: Any) -> dict[str, Any]:
    """Effective LQA settings of an org (defaults merged with org.settings["lqa"])."""
    out = default_settings()
    raw = ((getattr(org, "settings", None) or {}).get("lqa")) or {}
    if raw.get("threshold") is not None:
        out["threshold"] = float(raw["threshold"])
    for dim, w in (raw.get("weights") or {}).items():
        if dim in DIMENSIONS:
            out["weights"][dim] = float(w)
    return out


def validate_settings(threshold: float | None, weights: dict[str, float] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if threshold is not None:
        if not 0 <= threshold <= 100:
            raise ValueError("threshold must be between 0 and 100")
        out["threshold"] = float(threshold)
    if weights is not None:
        bad = [d for d in weights if d not in DIMENSIONS]
        if bad:
            raise ValueError(f"unknown dimension {bad[0]!r}; use one of {', '.join(DIMENSIONS)}")
        if any(not 0 <= float(w) <= 10 for w in weights.values()):
            raise ValueError("dimension weights must be between 0 and 10")
        out["weights"] = {d: float(w) for d, w in weights.items()}
    return out


def normalize_error(e: dict[str, Any], source: str) -> dict[str, Any] | None:
    """One error from a reviewer, the senate, the judge or a hard check -> scorecard row."""
    sev = str(e.get("severity") or "").lower()
    if sev not in SEVERITIES:
        return None
    dim = _norm_dimension(e.get("dimension") or e.get("category")) or "other"
    return {
        "dimension": dim,
        "severity": sev,
        "span": str(e.get("span") or ""),
        "explanation": str(e.get("explanation") or e.get("message") or ""),
        "source": source,
    }


def scorecard(errors: Iterable[dict[str, Any]], word_count: int, settings: dict[str, Any]) -> dict[str, Any]:
    weights: dict[str, float] = settings.get("weights") or {}
    threshold = float(settings.get("threshold", DEFAULT_THRESHOLD))
    counts: dict[str, dict[str, Any]] = {
        d: {**dict.fromkeys(SEVERITIES, 0), "penalty": 0.0} for d in DIMENSIONS
    }
    by_severity = dict.fromkeys(SEVERITIES, 0)
    total = 0
    penalty = 0.0
    for e in errors:
        dim = e["dimension"] if e["dimension"] in counts else "other"
        sev = e["severity"]
        counts[dim][sev] += 1
        by_severity[sev] += 1
        p = SEVERITY_WEIGHT.get(sev, 0) * float(weights.get(dim, 1.0))
        counts[dim]["penalty"] = round(counts[dim]["penalty"] + p, 4)
        penalty += p
        total += 1
    words = max(int(word_count), 1)
    score = round(min(100.0, max(0.0, 100.0 - penalty * 100.0 / words)), 2)
    return {
        "word_count": int(word_count),
        "error_count": total,
        "by_dimension": counts,
        "by_severity": by_severity,
        "penalty": round(penalty, 4),
        "score": score,
        "threshold": threshold,
        "passed": score >= threshold,
        "weights": {d: float(weights.get(d, 1.0)) for d in DIMENSIONS},
    }


# --------------------------------------------------------------------------- exports


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def to_pdf(title: str, meta: list[str], card: dict[str, Any], rows: list[dict[str, Any]]) -> bytes:
    """Scorecard PDF: header, verdict, dimension x severity table, then the error list."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), title=title)
    st = getSampleStyleSheet()
    small = st["BodyText"].clone("small", fontSize=7, leading=9)
    verdict = "PASS" if card["passed"] else "FAIL"
    story: list[Any] = [Paragraph(_esc(title), st["Title"])]
    for line in meta:
        story.append(Paragraph(_esc(line), st["BodyText"]))
    story.append(
        Paragraph(
            f"<b>MQM score {card['score']:.2f}</b> (pass threshold {card['threshold']:.2f}): <b>{verdict}</b> · "
            f"{card['error_count']} errors · penalty {card['penalty']:g} · {card['word_count']} words",
            st["BodyText"],
        )
    )
    story.append(Spacer(1, 8))
    head = ["Dimension", *[s.capitalize() for s in SEVERITIES], "Weight", "Penalty"]
    table = [head]
    for dim in DIMENSIONS:
        c = card["by_dimension"][dim]
        table.append(
            [
                dim.replace("_", " "),
                *[str(c[s]) for s in SEVERITIES],
                f"{card['weights'][dim]:g}",
                f"{c['penalty']:g}",
            ]
        )
    table.append(["Total", *[str(card["by_severity"][s]) for s in SEVERITIES], "", f"{card['penalty']:g}"])
    t = Table(table, repeatRows=1)
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
    ]
    t.setStyle(TableStyle(style))
    story += [t, Spacer(1, 10)]
    if rows:
        er = [["#", "Dimension", "Severity", "Source", "Span", "Explanation", "Origin"]]
        for r in rows[:2000]:
            er.append(
                [
                    str(r.get("seq", "")),
                    r["dimension"].replace("_", " "),
                    r["severity"],
                    Paragraph(_esc(str(r.get("source_text", ""))[:300]), small),
                    Paragraph(_esc(r.get("span", "")[:200]), small),
                    Paragraph(_esc(r.get("explanation", "")[:400]), small),
                    r.get("source", ""),
                ]
            )
        et = Table(er, colWidths=[25, 80, 50, 210, 120, 220, 55], repeatRows=1)
        et.setStyle(
            TableStyle([*style, ("VALIGN", (0, 0), (-1, -1), "TOP"), ("FONTSIZE", (0, 0), (-1, -1), 7)])
        )
        story.append(et)
    doc.build(story)
    return buf.getvalue()


def safe_cell(value: Any) -> Any:
    """Text from files and reviewers must never become a spreadsheet formula."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def to_xlsx(title: str, meta: list[str], card: dict[str, Any], rows: list[dict[str, Any]]) -> bytes:
    """Workbook with a Summary sheet (scorecard) and an Errors sheet (one row per error)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append([safe_cell(title)])
    ws["A1"].font = Font(bold=True, size=14)
    for line in meta:
        ws.append([safe_cell(line)])
    ws.append([])
    ws.append(["MQM score", card["score"]])
    ws.append(["Pass threshold", card["threshold"]])
    ws.append(["Verdict", "pass" if card["passed"] else "fail"])
    ws.append(["Errors", card["error_count"]])
    ws.append(["Penalty", card["penalty"]])
    ws.append(["Words", card["word_count"]])
    ws.append([])
    header = ["Dimension", *SEVERITIES, "Weight", "Penalty"]
    ws.append(header)
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)
    for dim in DIMENSIONS:
        c = card["by_dimension"][dim]
        ws.append([dim, *[c[s] for s in SEVERITIES], card["weights"][dim], c["penalty"]])
    ws.append(["total", *[card["by_severity"][s] for s in SEVERITIES], None, card["penalty"]])
    ws.column_dimensions["A"].width = 28

    es = wb.create_sheet("Errors")
    es.append(["#", "Dimension", "Severity", "Source text", "Target text", "Span", "Explanation", "Origin"])
    for cell in es[1]:
        cell.font = Font(bold=True)
    for r in rows:
        es.append(
            [
                r.get("seq"),
                r["dimension"],
                r["severity"],
                safe_cell(r.get("source_text", "")),
                safe_cell(r.get("target_text", "")),
                safe_cell(r.get("span", "")),
                safe_cell(r.get("explanation", "")),
                r.get("source", ""),
            ]
        )
    for col, width in zip("ABCDEFGH", (6, 22, 10, 50, 50, 30, 50, 12), strict=True):
        es.column_dimensions[col].width = width
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
