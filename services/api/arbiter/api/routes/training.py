"""Own models (module "engine", add-on custom_models): training data preview, training jobs,
custom models. Writes need `engines.manage`. See arbiter.training.service."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from arbiter import storage
from arbiter.api.deps import DB, PM, require_module, require_permission
from arbiter.engines.catalog import TRAINING_PROVIDERS
from arbiter.errors import Invalid, NotFound
from arbiter.models import CustomModel, EngineScore, TrainingJob
from arbiter.platform.modules import org_has_addon
from arbiter.training import service

router = APIRouter(tags=["training"], dependencies=[require_module("engine")])
MANAGE = [require_permission("engines.manage")]


class DatasetIn(BaseModel):
    source_lang: str = Field(min_length=2, max_length=16)
    target_lang: str = Field(min_length=2, max_length=16)
    domain: str = Field(default="general", max_length=60)


class TrainingJobIn(DatasetIn):
    provider: str = Field(default="manual", max_length=40)
    base_model: str = Field(min_length=1, max_length=200)


class CustomModelIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    source_lang: str = Field(min_length=2, max_length=16)
    target_lang: str = Field(min_length=2, max_length=16)
    domain: str = Field(default="general", max_length=60)
    endpoint: str = Field(min_length=8, max_length=400)
    provider_model_id: str = Field(min_length=1, max_length=300)
    credential_id: str | None = Field(default=None, max_length=40)
    region: Literal["eu", "us", "global"] = "global"
    base_model: str = Field(default="", max_length=200)
    training_job_id: str | None = Field(default=None, max_length=40)


def _addon(p: PM) -> None:
    if not org_has_addon(p.org, "custom_models"):
        raise Invalid("own models are not enabled for this organization")


def job_view(j: TrainingJob) -> dict[str, Any]:
    return {
        "id": j.id,
        "source_lang": j.source_lang,
        "target_lang": j.target_lang,
        "domain": j.domain,
        "provider": j.provider,
        "base_model": j.base_model,
        "state": j.state,
        "dataset_stats": j.dataset_stats,
        "cost": str(j.cost),
        "currency": j.currency,
        "result_model_id": j.result_model_id,
        "endpoint": j.endpoint,
        "custom_model_id": j.custom_model_id,
        "error": j.error,
        "created_at": j.created_at.isoformat() if j.created_at else None,
        "finished_at": j.finished_at.isoformat() if j.finished_at else None,
    }


def model_view(m: CustomModel, score: EngineScore | None = None) -> dict[str, Any]:
    return {
        "id": m.id,
        "engine": m.engine_name,
        "name": m.name,
        "source_lang": m.source_lang,
        "target_lang": m.target_lang,
        "domain": m.domain,
        "base_model": m.base_model,
        "provider_model_id": m.provider_model_id,
        "endpoint": m.endpoint,
        "region": m.region,
        "active": m.active,
        "training_job_id": m.training_job_id,
        "scoreboard": (
            {
                "mean_qe": round(score.mean_qe, 2),
                "mean_edit_distance": round(score.mean_edit_distance, 4),
                "segments_measured": score.segments_measured,
            }
            if score
            else None
        ),
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


@router.post("/training/datasets/preview")
def preview(body: DatasetIn, p: PM, db: DB) -> dict[str, Any]:
    assert p.org is not None
    return service.preview(db, p.org, body.source_lang, body.target_lang, body.domain)


@router.get("/training/jobs")
def list_jobs(p: PM, db: DB) -> dict[str, Any]:
    return {"items": [job_view(j) for j in service.list_jobs(db, p.org_id)], "next_offset": None}


@router.post("/training/jobs", status_code=201, dependencies=MANAGE)
def start(body: TrainingJobIn, p: PM, db: DB) -> dict[str, Any]:
    _addon(p)
    assert p.org is not None
    if body.provider not in TRAINING_PROVIDERS:
        raise Invalid(f"provider must be one of {', '.join(TRAINING_PROVIDERS)}")
    job = service.start_job(
        db,
        p.org,
        source_lang=body.source_lang,
        target_lang=body.target_lang,
        domain=body.domain,
        provider=body.provider,
        base_model=body.base_model,
        actor=p.user.id if p.user else None,
    )
    return job_view(job)


@router.get("/training/jobs/{job_id}")
def get_job(job_id: str, p: PM, db: DB) -> dict[str, Any]:
    return job_view(service._job(db, job_id, p.org_id))  # noqa: SLF001


@router.post("/training/jobs/{job_id}/refresh", dependencies=MANAGE)
def refresh(job_id: str, p: PM, db: DB) -> dict[str, Any]:
    return job_view(service.refresh(db, job_id, org_id=p.org_id))


@router.get("/training/jobs/{job_id}/dataset", dependencies=MANAGE)
def download_dataset(
    job_id: str, p: PM, db: DB, split: Literal["train", "validation"] = Query(default="train")
) -> Response:
    job = service._job(db, job_id, p.org_id)  # noqa: SLF001
    key = job.train_storage_key if split == "train" else job.validation_storage_key
    if not key:
        raise NotFound("dataset not found")
    return Response(
        storage.get(key),
        media_type="application/jsonl",
        headers={"content-disposition": f'attachment; filename="{job.id}-{split}.jsonl"'},
    )


@router.get("/custom-models")
def list_models(p: PM, db: DB) -> dict[str, Any]:
    models = list(
        db.execute(
            select(CustomModel).where(CustomModel.org_id == p.org_id).order_by(CustomModel.created_at.desc())
        ).scalars()
    )
    names = [m.engine_name for m in models]
    scores: dict[str, EngineScore] = {}
    if names:
        for s in db.execute(select(EngineScore).where(EngineScore.engine.in_(names))).scalars():
            scores[s.engine] = s
    return {"items": [model_view(m, scores.get(m.engine_name)) for m in models], "next_offset": None}


@router.post("/custom-models", status_code=201, dependencies=MANAGE)
def register(body: CustomModelIn, p: PM, db: DB) -> dict[str, Any]:
    from arbiter.engines.manage import check_endpoint

    _addon(p)
    assert p.org is not None
    model = service.register_model(
        db,
        p.org,
        name=body.name,
        source_lang=body.source_lang,
        target_lang=body.target_lang,
        domain=body.domain,
        endpoint=check_endpoint(body.endpoint, allow_private=False),
        provider_model_id=body.provider_model_id,
        credential_id=body.credential_id,
        region=body.region,
        base_model=body.base_model,
        training_job_id=body.training_job_id,
    )
    return model_view(model)


@router.post("/custom-models/{model_id}/activate", dependencies=MANAGE)
def activate(model_id: str, p: PM, db: DB) -> dict[str, Any]:
    assert p.org is not None
    return model_view(service.set_active(db, p.org, model_id, True))


@router.post("/custom-models/{model_id}/deactivate", dependencies=MANAGE)
def deactivate(model_id: str, p: PM, db: DB) -> dict[str, Any]:
    assert p.org is not None
    return model_view(service.set_active(db, p.org, model_id, False))
