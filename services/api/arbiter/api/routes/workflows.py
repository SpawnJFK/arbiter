"""Workflow templates (Agency OS). Roles: pm or API key.

The first GET /workflows seeds the built-in presets for the org. DELETE archives: projects
and accounts keep their reference and running jobs keep their frozen snapshot.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header
from sqlalchemy import select

from arbiter.agency import workflows as wfl
from arbiter.agency.schemas import WorkflowIn, WorkflowPatch
from arbiter.api.deps import DB, PM, Paging, listing
from arbiter.api.routes.projects import idempotent_post
from arbiter.models import WorkflowTemplate

router = APIRouter(tags=["workflows"])


@router.get("/workflows")
def list_workflows(p: PM, db: DB, pg: Paging, include_archived: bool = False) -> dict[str, Any]:
    assert p.org is not None
    wfl.ensure_presets(db, p.org)
    stmt = select(WorkflowTemplate).where(WorkflowTemplate.org_id == p.org_id)
    if not include_archived:
        stmt = stmt.where(WorkflowTemplate.archived_at.is_(None))
    rows = list(
        db.execute(
            stmt.order_by(
                WorkflowTemplate.preset_key.is_(None).desc(),
                WorkflowTemplate.created_at,
                WorkflowTemplate.id,
            )
            .offset(pg.offset)
            .limit(pg.limit + 1)
        ).scalars()
    )
    return listing([wfl.workflow_view(w, p.org) for w in rows], pg)


@router.post("/workflows", status_code=201)
def create_workflow(
    body: WorkflowIn, p: PM, db: DB, idempotency_key: Annotated[str | None, Header()] = None
) -> Any:
    def make() -> dict[str, Any]:
        assert p.org is not None
        return wfl.workflow_view(wfl.create_workflow(db, p.org, body), p.org)

    return idempotent_post(db, p, "workflows", idempotency_key, body.model_dump(mode="json"), make)


@router.get("/workflows/{workflow_id}")
def get_workflow(workflow_id: str, p: PM, db: DB) -> dict[str, Any]:
    return wfl.workflow_view(wfl.get_workflow(db, p.org_id, workflow_id, include_archived=True), p.org)


@router.patch("/workflows/{workflow_id}")
def patch_workflow(workflow_id: str, body: WorkflowPatch, p: PM, db: DB) -> dict[str, Any]:
    assert p.org is not None
    wf = wfl.update_workflow(db, p.org, wfl.get_workflow(db, p.org_id, workflow_id), body)
    return wfl.workflow_view(wf, p.org)


@router.delete("/workflows/{workflow_id}")
def delete_workflow(workflow_id: str, p: PM, db: DB) -> dict[str, Any]:
    wf = wfl.get_workflow(db, p.org_id, workflow_id, include_archived=True)
    return wfl.workflow_view(wfl.archive_workflow(db, wf), p.org)
