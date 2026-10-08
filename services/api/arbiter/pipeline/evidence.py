"""Evidence pack: what happened to every segment of a delivered job, and why.

This is the product's answer to "how do I know the AI didn't ship garbage": per segment
the origin (TM / engine / editor / human), the QE score and threshold, the senate verdict,
the reviewer decision and the full provenance trail. Policies that changed the outcome
(no_reviewer_policy fallbacks, unreviewed segments in `partial`) are stated explicitly.
"""

from __future__ import annotations

import io
from collections import Counter
from typing import Any

import orjson
from sqlalchemy import select
from sqlalchemy.orm import Session

from arbiter.models import Job, Organization, ProvenanceEvent, Segment, SenateRun, utcnow
from arbiter.quality.prompts import PROMPT_VERSION

DECISION_LABEL = {
    "auto_approve": "Approved automatically (QE above threshold)",
    "reviewed": "Reviewed by a human reviewer",
    "ai_reviewed": "AI review (senate + editor), as ordered",
    "ai_fallback": "AI review because no reviewer was available before the deadline (org policy)",
    "unreviewed": "Delivered unreviewed: no reviewer before the deadline (org policy 'partial')",
}


def build(session: Session, job: Job) -> dict[str, Any]:
    org = session.get(Organization, job.org_id)
    segs = list(
        session.execute(select(Segment).where(Segment.job_id == job.id).order_by(Segment.seq)).scalars()
    )
    prov: dict[str | None, list[dict[str, Any]]] = {}
    for ev in session.execute(
        select(ProvenanceEvent).where(ProvenanceEvent.job_id == job.id).order_by(ProvenanceEvent.at)
    ).scalars():
        prov.setdefault(ev.segment_id, []).append(
            {
                "at": ev.at.isoformat(),
                "event": ev.event,
                "actor_type": ev.actor_type,
                "actor_id": ev.actor_id,
                "model_version": ev.model_version,
                "data": ev.data,
            }
        )
    senate = {
        r.segment_id: r
        for r in session.execute(select(SenateRun).where(SenateRun.job_id == job.id)).scalars()
    }
    decisions = Counter(s.decision or "unknown" for s in segs)
    return {
        "schema": "arbiter.evidence/1",
        "generated_at": utcnow().isoformat(),
        "job": {
            "id": job.id,
            "project_id": job.project_id,
            "pair": f"{job.source_lang}->{job.target_lang}",
            "tier": job.tier,
            "content_type": job.content_type,
            "segments": job.segment_count,
            "words": job.word_count,
            "glossary_version": job.glossary_version,
            "threshold": job.threshold,
            "band_width": job.band_width,
            "prompt_version": PROMPT_VERSION,
            "delivered_at": job.delivered_at.isoformat() if job.delivered_at else None,
            "no_reviewer_fallback_used": job.no_reviewer_fallback_used,
            "org_policy": {
                "no_reviewer_policy": org.no_reviewer_policy if org else None,
                "regulated": org.regulated if org else None,
            },
        },
        "summary": {
            "decisions": dict(decisions),
            "auto_approved": job.auto_approved_count,
            "human_reviewed": sum(1 for s in segs if s.decision == "reviewed"),
            "ai_reviewed": job.ai_reviewed_count,
            "control_samples": sum(1 for s in segs if s.is_control_sample),
        },
        "job_events": prov.get(None, []),
        "segments": [
            {
                "id": s.id,
                "seq": s.seq,
                "source": s.source_tagged,
                "target": s.target_tagged,
                "origin": s.origin,
                "engine": s.engine,
                "tm_match": s.tm_match,
                "qe_score": s.qe_score,
                "decision": s.decision,
                "decision_label": DECISION_LABEL.get(s.decision or "", s.decision),
                "reasons": s.reasons,
                "reviewer": s.reviewer_id,
                "senate": (
                    {
                        "outcome": senate[s.id].outcome,
                        "roles": f"{senate[s.id].roles_answered}/{senate[s.id].roles_total}",
                        "confirmed": senate[s.id].confirmed,
                    }
                    if s.id in senate
                    else None
                ),
                "provenance": prov.get(s.id, []),
            }
            for s in segs
        ],
    }


def to_json(pack: dict[str, Any]) -> bytes:
    return orjson.dumps(pack, option=orjson.OPT_INDENT_2)


def to_pdf(pack: dict[str, Any]) -> bytes:
    """A readable summary for people who will never open the JSON."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), title=f"Evidence {pack['job']['id']}")
    st = getSampleStyleSheet()
    small = st["BodyText"].clone("small", fontSize=7, leading=9)
    j, summ = pack["job"], pack["summary"]
    story: list[Any] = [
        Paragraph(f"Evidence pack: job {j['id']}", st["Title"]),
        Paragraph(
            f"Pair {j['pair']} · tier {j['tier']} · content {j['content_type']} · {j['segments']} segments · "
            f"{j['words']} words · threshold {j['threshold']} (band {j['band_width']}) · "
            f"glossary v{j['glossary_version']} · prompts {j['prompt_version']}",
            st["BodyText"],
        ),
        Paragraph(
            f"Auto-approved {summ['auto_approved']} · human reviewed {summ['human_reviewed']} · "
            f"AI reviewed {summ['ai_reviewed']} · blind control samples {summ['control_samples']}",
            st["BodyText"],
        ),
    ]
    if j["no_reviewer_fallback_used"]:
        story.append(
            Paragraph(
                f"<b>Note:</b> no reviewer was available before the deadline; the organisation policy "
                f"'{j['org_policy']['no_reviewer_policy']}' was applied to the affected segments (marked below).",
                st["BodyText"],
            )
        )
    story.append(Spacer(1, 8))
    rows = [["#", "Source", "Target", "Origin", "QE", "Decision"]]
    for s in pack["segments"]:
        rows.append(
            [
                str(s["seq"] + 1),
                Paragraph(_esc(s["source"]), small),
                Paragraph(_esc(s["target"] or ""), small),
                s["origin"] or "",
                "" if s["qe_score"] is None else f"{s['qe_score']:.0f}",
                Paragraph(_esc(s["decision_label"] or ""), small),
            ]
        )
    t = Table(rows, colWidths=[25, 280, 280, 45, 30, 120], repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(t)
    doc.build(story)
    return buf.getvalue()


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
