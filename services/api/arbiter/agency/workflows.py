"""Workflow templates: validation, built-in presets, the snapshot a job freezes.

Step kinds (docs/api-contract.md, Agency OS):
  tm                  TM pre-translation (context/exact matches)
  mt                  machine translation; params.engine prefers one engine
  translation_senate  best-of-N translation across engines (forces it for the job)
  qe                  quality estimation; params.threshold (0..100) overrides the job threshold
  senate              review senate for the uncertain band
  ai_review           senate + AI editor instead of a human (ai_review tier)
  human_review        a human reviewer; params.min_level (reviewer | senior | domain_expert)
  second_review       a second, senior human after the first review
  client_review       the job waits for the client's approval before delivery
  delivery            merge and deliver

Validation (contract + consistency rules):
  * must contain mt, tm or translation_senate (a TM-only workflow needs human_review: segments
    without a TM match are translated by the reviewer)
  * each kind at most once; delivery present and last
  * translation steps (tm, mt, translation_senate) come before qe
  * qe present and before any review step (senate, ai_review, human_review, second_review,
    client_review)
  * second_review needs human_review before it
  * tier consistency: full => human_review; auto => no human_review/second_review/ai_review;
    ai_review => no human_review/second_review (the client bought AI review, not a human)
  * R-SEG-12: a regulated org rejects tier auto and ai_review
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from arbiter.agency.common import HUMANLESS_TIERS, REGULATED_REASON, iso
from arbiter.agency.schemas import StepIn, WorkflowIn, WorkflowPatch
from arbiter.errors import Invalid, NotFound
from arbiter.models import Organization, WorkflowTemplate, utcnow

TRANSLATION_STEPS = ("tm", "mt", "translation_senate")
REVIEW_STEPS = ("senate", "ai_review", "human_review", "second_review", "client_review")
HUMAN_STEPS = ("human_review", "second_review")
LEVELS = ("reviewer", "senior", "domain_expert")
ENGINE_NAME_MAX = 80


class WorkflowInvalid(Invalid):
    code = "workflow_invalid"


def _s(kind: str, **params: Any) -> dict[str, Any]:
    return {"kind": kind, "params": params}


# key -> (name, description, tier, steps)
PRESETS: dict[str, tuple[str, str, str, list[dict[str, Any]]]] = {
    "machine_only": (
        "Machine only",
        "TM, machine translation and QE; segments ship automatically when the score allows.",
        "auto",
        [_s("tm"), _s("mt"), _s("qe"), _s("delivery")],
    ),
    "ai_reviewed": (
        "AI reviewed",
        "TM, MT and QE; uncertain segments go to the senate and the AI editor, no human.",
        "ai_review",
        [_s("tm"), _s("mt"), _s("qe"), _s("ai_review"), _s("delivery")],
    ),
    "hybrid": (
        "Hybrid (MT+QE+human for low scores)",
        "TM, MT and QE; high scores ship, the band goes to the senate, low scores to a human.",
        "hybrid",
        [_s("tm"), _s("mt"), _s("qe"), _s("senate"), _s("human_review"), _s("delivery")],
    ),
    "full_review": (
        "Full human review",
        "TM, MT and QE as guidance; a human reviews every segment.",
        "full",
        [_s("tm"), _s("mt"), _s("qe"), _s("human_review"), _s("delivery")],
    ),
    "regulated": (
        "Regulated: two reviewers + client approval",
        "Every segment reviewed by a senior human, then a second senior reviewer; "
        "the client approves before delivery.",
        "full",
        [
            _s("tm"),
            _s("mt"),
            _s("qe"),
            _s("human_review", min_level="senior"),
            _s("second_review"),
            _s("client_review"),
            _s("delivery"),
        ],
    ),
}

# What a job without a template runs: the steps that describe today's tier behaviour exactly.
TIER_STEPS: dict[str, list[dict[str, Any]]] = {
    "auto": [_s("tm"), _s("mt"), _s("qe"), _s("senate"), _s("delivery")],
    "ai_review": [_s("tm"), _s("mt"), _s("qe"), _s("ai_review"), _s("delivery")],
    "hybrid": [_s("tm"), _s("mt"), _s("qe"), _s("senate"), _s("human_review"), _s("delivery")],
    "full": [_s("tm"), _s("mt"), _s("qe"), _s("human_review"), _s("delivery")],
}


# --------------------------------------------------------------------------- validation


def _params(kind: str, params: dict[str, Any]) -> dict[str, Any]:
    allowed: dict[str, tuple[str, ...]] = {
        "mt": ("engine",),
        "qe": ("threshold",),
        "human_review": ("min_level",),
        "second_review": ("min_level",),
    }
    keys = allowed.get(kind, ())
    unknown = [k for k in params if k not in keys]
    if unknown:
        raise WorkflowInvalid(f"step {kind} does not take parameter(s): {', '.join(unknown)}")
    out: dict[str, Any] = {}
    if kind == "mt" and params.get("engine") is not None:
        engine = params["engine"]
        if not isinstance(engine, str) or not engine.strip() or len(engine) > ENGINE_NAME_MAX:
            raise WorkflowInvalid("mt.params.engine must be an engine name")
        out["engine"] = engine.strip()
    if kind == "qe" and params.get("threshold") is not None:
        thr = params["threshold"]
        if isinstance(thr, bool) or not isinstance(thr, (int, float)) or not 0 <= float(thr) <= 100:
            raise WorkflowInvalid("qe.params.threshold must be a number between 0 and 100")
        out["threshold"] = float(thr)
    if kind in ("human_review", "second_review") and params.get("min_level") is not None:
        if params["min_level"] not in LEVELS:
            raise WorkflowInvalid(f"{kind}.params.min_level must be one of {', '.join(LEVELS)}")
        out["min_level"] = params["min_level"]
    return out


def validate_steps(
    steps: list[StepIn] | list[dict[str, Any]], tier: str, *, regulated: bool
) -> list[dict[str, Any]]:
    """Normalised steps [{kind, params}] or WorkflowInvalid (422) naming the broken rule."""
    norm: list[dict[str, Any]] = []
    for st in steps:
        raw = st.model_dump() if isinstance(st, StepIn) else StepIn.model_validate(st).model_dump()
        norm.append({"kind": raw["kind"], "params": _params(raw["kind"], raw.get("params") or {})})
    kinds = [s["kind"] for s in norm]
    pos = {k: i for i, k in enumerate(kinds)}
    dupes = sorted({k for k in kinds if kinds.count(k) > 1})
    if dupes:
        raise WorkflowInvalid(f"each step may appear once: {', '.join(dupes)} repeated")
    if not any(k in pos for k in TRANSLATION_STEPS):
        raise WorkflowInvalid("a workflow must contain mt or tm")
    if "delivery" not in pos or kinds[-1] != "delivery":
        raise WorkflowInvalid("delivery must be the last step")
    reviews = [k for k in kinds if k in REVIEW_STEPS]
    if reviews and "qe" not in pos:
        raise WorkflowInvalid("qe must come before any review step")
    if "qe" in pos:
        late = [k for k in TRANSLATION_STEPS if k in pos and pos[k] > pos["qe"]]
        if late:
            raise WorkflowInvalid(f"{', '.join(late)} must come before qe")
        early = [k for k in reviews if pos[k] < pos["qe"]]
        if early:
            raise WorkflowInvalid(f"qe must come before any review step ({', '.join(early)} is before qe)")
    if "second_review" in pos and ("human_review" not in pos or pos["human_review"] > pos["second_review"]):
        raise WorkflowInvalid("second_review needs a human_review step before it")
    if "mt" not in pos and "translation_senate" not in pos and "human_review" not in pos:
        raise WorkflowInvalid(
            "a TM-only workflow needs human_review (unmatched segments are translated by a human)"
        )
    humans = [k for k in HUMAN_STEPS if k in pos]
    if tier == "full" and "human_review" not in pos:
        raise WorkflowInvalid("tier full needs a human_review step")
    if tier == "auto" and (humans or "ai_review" in pos):
        raise WorkflowInvalid("tier auto cannot contain human_review, second_review or ai_review")
    if tier == "ai_review" and humans:
        raise WorkflowInvalid("tier ai_review cannot contain human_review or second_review")
    if regulated and tier in HUMANLESS_TIERS:
        raise WorkflowInvalid(f"the {tier} tier is not available: {REGULATED_REASON}")
    return norm


# --------------------------------------------------------------------------- CRUD


def get_workflow(
    session: Session, org_id: str, wf_id: str, *, include_archived: bool = False
) -> WorkflowTemplate:
    wf = session.execute(
        select(WorkflowTemplate).where(WorkflowTemplate.id == wf_id, WorkflowTemplate.org_id == org_id)
    ).scalar_one_or_none()
    if wf is None or (wf.archived_at is not None and not include_archived):
        raise NotFound("workflow not found")
    return wf


def find_by_name(session: Session, org_id: str, name: str) -> WorkflowTemplate | None:
    return (
        session.execute(
            select(WorkflowTemplate).where(
                WorkflowTemplate.org_id == org_id,
                func.lower(WorkflowTemplate.name) == name.strip().lower(),
                WorkflowTemplate.archived_at.is_(None),
            )
        )
        .scalars()
        .first()
    )


def _clear_default(session: Session, org_id: str, keep: str) -> None:
    session.execute(
        update(WorkflowTemplate)
        .where(WorkflowTemplate.org_id == org_id, WorkflowTemplate.id != keep)
        .values(is_default=False)
    )


def create_workflow(session: Session, org: Organization, body: WorkflowIn) -> WorkflowTemplate:
    steps = validate_steps(body.steps, body.tier, regulated=org.regulated)
    wf = WorkflowTemplate(
        org_id=org.id,
        name=body.name,
        description=body.description,
        content_type=(body.content_type or None),
        tier=body.tier,
        steps=steps,
        is_default=body.is_default,
    )
    session.add(wf)
    session.flush()
    if body.is_default:
        _clear_default(session, org.id, wf.id)
    return wf


def update_workflow(
    session: Session, org: Organization, wf: WorkflowTemplate, body: WorkflowPatch
) -> WorkflowTemplate:
    """Editing a template never changes running jobs: they keep their frozen snapshot."""
    data = body.model_dump(exclude_unset=True)
    for key in ("name", "tier", "steps"):
        if key in data and data[key] is None:
            raise Invalid(f"{key} cannot be null")
    tier = data.get("tier", wf.tier)
    steps_in = body.steps if "steps" in data else wf.steps
    steps = validate_steps(steps_in or [], tier, regulated=org.regulated)
    if "name" in data:
        wf.name = data["name"]
    if "description" in data:
        wf.description = data["description"] or ""
    if "content_type" in data:
        wf.content_type = data["content_type"] or None
    wf.tier, wf.steps = tier, steps
    if data.get("is_default") is not None:
        wf.is_default = bool(data["is_default"])
        if wf.is_default:
            _clear_default(session, org.id, wf.id)
    wf.updated_at = utcnow()
    session.flush()
    return wf


def archive_workflow(session: Session, wf: WorkflowTemplate) -> WorkflowTemplate:
    """DELETE archives: projects and accounts keep their reference, jobs their snapshot."""
    wf.archived_at = wf.archived_at or utcnow()
    wf.is_default = False
    session.flush()
    return wf


def ensure_presets(session: Session, org: Organization) -> int:
    """Seed the built-in presets once per org (first GET /workflows). Returns how many were added."""
    have = set(
        session.execute(
            select(WorkflowTemplate.preset_key).where(
                WorkflowTemplate.org_id == org.id, WorkflowTemplate.preset_key.is_not(None)
            )
        ).scalars()
    )
    added = 0
    for key, (name, desc, tier, steps) in PRESETS.items():
        if key in have:
            continue
        session.add(
            WorkflowTemplate(
                org_id=org.id,
                name=name,
                description=desc,
                tier=tier,
                steps=[dict(s) for s in steps],
                is_default=False,
                preset_key=key,
            )
        )
        added += 1
    if added:
        session.flush()
    return added


def workflow_view(wf: WorkflowTemplate, org: Organization | None = None) -> dict[str, Any]:
    blocked = bool(org is not None and org.regulated and wf.tier in HUMANLESS_TIERS)
    return {
        "id": wf.id,
        "name": wf.name,
        "description": wf.description,
        "content_type": wf.content_type,
        "tier": wf.tier,
        "steps": [dict(s) for s in (wf.steps or [])],
        "is_default": wf.is_default,
        "preset": wf.preset_key,
        "archived": wf.archived_at is not None,
        "available": not blocked,
        "blocked_reason": REGULATED_REASON if blocked else None,
        "created_at": iso(wf.created_at),
        "updated_at": iso(wf.updated_at),
    }


# --------------------------------------------------------------------------- job snapshot


def snapshot(wf: WorkflowTemplate | None, tier: str) -> dict[str, Any]:
    """What job.workflow freezes at project creation."""
    if wf is not None:
        return {
            "template_id": wf.id,
            "name": wf.name,
            "tier": wf.tier,
            "source": "template",
            "steps": [dict(s) for s in (wf.steps or [])],
        }
    return {
        "template_id": None,
        "name": f"{tier} (tier default)",
        "tier": tier,
        "source": "tier",
        "steps": [dict(s) for s in TIER_STEPS[tier]],
    }


def step(workflow: dict[str, Any] | None, kind: str) -> dict[str, Any] | None:
    """The step of that kind in a job's snapshot, or None (also None for jobs without workflow)."""
    if not workflow:
        return None
    for st in workflow.get("steps") or []:
        if st.get("kind") == kind:
            return st
    return None


def has(workflow: dict[str, Any] | None, kind: str) -> bool:
    return step(workflow, kind) is not None
