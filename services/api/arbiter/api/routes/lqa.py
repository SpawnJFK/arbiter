"""LQA scorecards (module ai): MQM scorecard per job, PDF/XLSX export, org LQA settings."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from arbiter.api.deps import DB, PM, Customer, require_module
from arbiter.api.routes.jobs import attachment, get_job
from arbiter.errors import Invalid
from arbiter.models import FileAsset
from arbiter.quality import lqa, scorecard

router = APIRouter(tags=["lqa"], dependencies=[require_module("ai")])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/jobs/{job_id}/lqa")
def job_lqa(job_id: str, p: Customer, db: DB) -> dict[str, Any]:
    """Scorecard from reviewer errors and senate-confirmed errors (deduplicated)."""
    job = get_job(db, p, job_id)
    card, rows = lqa.job_scorecard(db, job)
    return {**card, "errors": rows}


def _export(db: Any, p: Any, job_id: str, kind: str) -> Response:
    job = get_job(db, p, job_id)
    card, rows = lqa.job_scorecard(db, job)
    fa = db.get(FileAsset, job.file_id)
    title = f"LQA scorecard: {fa.filename if fa else job.id} ({job.target_lang})"
    meta = lqa.meta_lines(job, fa.filename if fa else None)
    if kind == "pdf":
        data, media = scorecard.to_pdf(title, meta, card, rows), "application/pdf"
    else:
        data, media = scorecard.to_xlsx(title, meta, card, rows), XLSX
    return Response(
        data, media_type=media, headers={"Content-Disposition": attachment(f"lqa-{job.id}.{kind}")}
    )


@router.get("/jobs/{job_id}/lqa.pdf")
def job_lqa_pdf(job_id: str, p: Customer, db: DB) -> Response:
    return _export(db, p, job_id, "pdf")


@router.get("/jobs/{job_id}/lqa.xlsx")
def job_lqa_xlsx(job_id: str, p: Customer, db: DB) -> Response:
    return _export(db, p, job_id, "xlsx")


@router.get("/lqa/settings")
def lqa_settings(p: Customer, db: DB) -> dict[str, Any]:
    return {**scorecard.settings_for(p.org), "dimensions": list(scorecard.DIMENSIONS)}


class LqaSettingsIn(BaseModel):
    threshold: float | None = Field(default=None, ge=0, le=100)
    weights: dict[str, float] | None = None
    reset: bool = False


@router.put("/lqa/settings")
def put_lqa_settings(body: LqaSettingsIn, p: PM, db: DB) -> dict[str, Any]:
    """Org pass threshold and per-dimension weight overrides; reset=true restores defaults."""
    org = p.org
    assert org is not None
    settings = dict(org.settings or {})
    if body.reset:
        settings.pop("lqa", None)
    else:
        try:
            changes = scorecard.validate_settings(body.threshold, body.weights)
        except ValueError as e:
            raise Invalid(str(e)) from None
        current = dict(settings.get("lqa") or {})
        if "threshold" in changes:
            current["threshold"] = changes["threshold"]
        if "weights" in changes:
            current["weights"] = {**(current.get("weights") or {}), **changes["weights"]}
        settings["lqa"] = current
    org.settings = settings
    db.flush()
    return {**scorecard.settings_for(org), "dimensions": list(scorecard.DIMENSIONS)}
