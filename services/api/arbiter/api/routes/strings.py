"""Software string localization (module `strings`), see docs/api-contract.md "Software strings".

Every /v1/strings route requires the `strings` module (404 module_disabled otherwise) and a
permission: strings.read for reads, strings.write for changes, strings.publish for releases
and distribution tokens. API keys work for CI (push / pull / releases).

The public OTA routes (no auth) are on `public_router`, mounted at the root: /ota/...
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, Header, Query, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from arbiter.api.deps import DB, Paging, Principal, listing, require_module, require_permission
from arbiter.api.routes.projects import idempotent_replay, idempotent_store
from arbiter.errors import Invalid, NotFound
from arbiter.models import StringBatch
from arbiter.strings import formats, releases, service, translate
from arbiter.strings.formats.base import StringsFormatError
from arbiter.strings.qa import check_value

router = APIRouter(tags=["strings"], dependencies=[require_module("strings")])
public_router = APIRouter(tags=["strings-ota"])

Reader = Annotated[Principal, require_permission("strings.read")]
Writer = Annotated[Principal, require_permission("strings.write")]
Publisher = Annotated[Principal, require_permission("strings.publish")]
MAX_UPLOAD = 20 * 1024 * 1024
KEYS_PAGE_MAX = 1000


def _actor(p: Principal) -> str:
    if p.user is not None:
        return p.user.id
    return p.api_key.id if p.api_key is not None else ""


def _fmt_error(e: StringsFormatError) -> Invalid:
    return Invalid(str(e), {"code": "unsupported_file"})


# ------------------------------------------------------------------ schemas


class ProjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    base_lang: str = Field(min_length=2, max_length=16)
    target_langs: list[str] = Field(default_factory=list, max_length=200)
    platforms: list[str] = Field(default_factory=list)
    tier: Literal["auto", "ai_review", "hybrid", "full"] | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class ProjectPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    target_langs: list[str] | None = None
    platforms: list[str] | None = None
    tier: Literal["auto", "ai_review", "hybrid", "full"] | None = None
    settings: dict[str, Any] | None = None


class KeyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=500)
    namespace: str = Field(default="", max_length=200)
    kind: Literal["string", "plural", "array"] = "string"
    description: str = Field(default="", max_length=5000)
    max_length: int | None = Field(default=None, ge=1, le=100000)
    tags: list[str] = Field(default_factory=list)
    screenshot_url: str | None = Field(default=None, max_length=1000)
    translatable: bool = True
    value: str | None = None
    forms: dict[str, str] | None = None


class KeyPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=500)
    namespace: str | None = Field(default=None, max_length=200)
    kind: Literal["string", "plural", "array"] | None = None
    description: str | None = Field(default=None, max_length=5000)
    max_length: int | None = Field(default=None, ge=1, le=100000)
    tags: list[str] | None = None
    screenshot_url: str | None = Field(default=None, max_length=1000)
    translatable: bool | None = None
    archived: bool | None = None


class TranslationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str | None = None
    forms: dict[str, str] | None = None
    state: Literal["machine", "reviewed", "approved"] | None = None


class BranchIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)


class MergeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolutions: dict[str, Literal["branch", "main"]] = Field(default_factory=dict)


class TranslateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    branch: str | None = None
    langs: list[str] | None = None
    mode: Literal["translate", "tm_only"] = "translate"
    key_ids: list[str] | None = Field(default=None, max_length=10000)


class BulkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[
        "approve", "clear", "pretranslate_tm", "translate", "archive", "unarchive", "tag", "untag"
    ]
    branch: str | None = None
    key_ids: list[str] | None = Field(default=None, max_length=10000)
    langs: list[str] | None = None
    tag: str | None = Field(default=None, max_length=100)


class ReleaseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    branch: str | None = None
    version_label: str | None = Field(default=None, max_length=64)
    langs: list[str] | None = None
    formats: list[str] = Field(default_factory=list)
    publish: bool = True


# ------------------------------------------------------------------ views


def project_view(db: DB, proj: Any, *, stats: bool = False) -> dict[str, Any]:
    s = service.settings_of(proj)
    s.pop("distribution_token_hash", None)
    out: dict[str, Any] = {
        "id": proj.id,
        "name": proj.name,
        "public_id": proj.public_id,
        "base_lang": proj.base_lang,
        "target_langs": proj.target_langs,
        "platforms": proj.platforms,
        "tier": proj.tier,
        "settings": s,
        "has_distribution_token": bool((proj.settings or {}).get("distribution_token_hash")),
        "ota_base": f"{releases.ota_base()}/ota/{proj.public_id}",
        "created_at": proj.created_at.isoformat() if proj.created_at else None,
    }
    if stats:
        out["stats"] = service.project_stats(db, proj)
    return out


def _langs_param(raw: str | None, proj: Any) -> list[str]:
    if not raw:
        return list(proj.target_langs)
    return [service.norm_locale(x) for x in raw.split(",") if x.strip()]


# ------------------------------------------------------------------ formats and projects


@router.get("/strings/formats")
def list_formats(p: Reader) -> dict[str, Any]:
    return {
        "items": [
            {
                "name": f.name,
                "label": f.label,
                "extension": f.extension,
                "multilingual": f.multilingual,
                "bilingual": f.bilingual,
            }
            for f in formats.FORMATS.values()
        ]
    }


@router.get("/strings/projects")
def list_projects(p: Reader, db: DB, pg: Paging) -> dict[str, Any]:
    rows = service.list_projects(db, p.org_id, pg.offset, pg.limit)
    return listing([project_view(db, r, stats=True) for r in rows], pg)


@router.post("/strings/projects", status_code=201)
def create_project(
    body: ProjectIn,
    p: Writer,
    db: DB,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Any:
    payload = body.model_dump()
    replay = idempotent_replay(db, p, "strings.project", idempotency_key, payload)
    if replay is not None:
        return replay
    assert p.org is not None
    proj = service.create_project(
        db,
        p.org,
        name=body.name,
        base_lang=body.base_lang,
        target_langs=body.target_langs,
        platforms=body.platforms,
        tier=body.tier,
        settings=body.settings,
        actor=_actor(p),
    )
    out = project_view(db, proj, stats=True)
    idempotent_store(db, p, "strings.project", idempotency_key, payload, 201, out)
    return out


@router.get("/strings/projects/{project_id}")
def get_project(project_id: str, p: Reader, db: DB) -> dict[str, Any]:
    return project_view(db, service.get_project(db, p.org_id, project_id), stats=True)


@router.patch("/strings/projects/{project_id}")
def patch_project(project_id: str, body: ProjectPatch, p: Writer, db: DB) -> dict[str, Any]:
    proj = service.get_project(db, p.org_id, project_id)
    assert p.org is not None
    service.update_project(db, p.org, proj, body.model_dump(exclude_none=True))
    return project_view(db, proj, stats=True)


@router.delete("/strings/projects/{project_id}", status_code=204)
def delete_project(project_id: str, p: Writer, db: DB) -> Response:
    proj = service.get_project(db, p.org_id, project_id)
    from arbiter.models import utcnow

    proj.archived_at = utcnow()
    return Response(status_code=204)


# ------------------------------------------------------------------ keys


@router.get("/strings/projects/{project_id}/keys")
def list_keys(
    project_id: str,
    p: Reader,
    db: DB,
    branch: str | None = None,
    q: str = "",
    tag: str | None = None,
    namespace: str | None = None,
    lang: str | None = None,
    state: Literal["untranslated", "machine", "reviewed", "approved", "blocked", "needs_review"]
    | None = None,
    langs: str | None = None,
    include_archived: bool = False,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1)] = 200,
) -> dict[str, Any]:
    proj = service.get_project(db, p.org_id, project_id)
    br = service.get_branch(db, proj, branch)
    query = service.KeyQuery(
        q=q,
        tag=tag,
        namespace=namespace,
        lang=service.norm_locale(lang) if lang else None,
        state=state,
        include_archived=include_archived,
        langs=_langs_param(langs, proj),
    )
    limit = min(limit, KEYS_PAGE_MAX)
    items, total = service.search_keys(db, proj, br, query, offset, limit)
    return {
        "items": items,
        "total": total,
        "next_offset": offset + limit if offset + limit < total else None,
        "branch": service.branch_view(db, br),
    }


@router.post("/strings/projects/{project_id}/keys", status_code=201)
def create_key(project_id: str, body: KeyIn, p: Writer, db: DB, branch: str | None = None) -> dict[str, Any]:
    proj = service.get_project(db, p.org_id, project_id)
    br = service.get_branch(db, proj, branch)
    base: Any = body.forms if body.kind != "string" else body.value
    if body.kind != "string" and body.forms is None and body.value is not None:
        base = {"other": body.value} if body.kind == "plural" else {"0": body.value}
    key = service.create_key(
        db,
        proj,
        br,
        name=body.name,
        namespace=body.namespace,
        kind=body.kind,
        description=body.description,
        max_length=body.max_length,
        tags=body.tags,
        screenshot_url=body.screenshot_url,
        translatable=body.translatable,
        base_value=base or None,
        actor=_actor(p),
    )
    return _key_out(db, proj, br, key)


def _key_out(db: Any, proj: Any, br: Any, key: Any, langs: list[str] | None = None) -> dict[str, Any]:
    langs = list(dict.fromkeys([proj.base_lang, *(langs or proj.target_langs)]))
    eff = service.effective(db, br, [key.id], langs)
    return service.key_view(key, eff, langs, br, proj)


@router.get("/strings/projects/{project_id}/keys/{key_id}")
def get_key(project_id: str, key_id: str, p: Reader, db: DB, branch: str | None = None) -> dict[str, Any]:
    proj = service.get_project(db, p.org_id, project_id)
    br = service.get_branch(db, proj, branch)
    return _key_out(db, proj, br, service.get_key(db, proj, key_id))


@router.patch("/strings/projects/{project_id}/keys/{key_id}")
def patch_key(
    project_id: str, key_id: str, body: KeyPatch, p: Writer, db: DB, branch: str | None = None
) -> dict[str, Any]:
    proj = service.get_project(db, p.org_id, project_id)
    br = service.get_branch(db, proj, branch)
    key = service.get_key(db, proj, key_id)
    changes = body.model_dump(exclude_unset=True)
    archived = changes.pop("archived", None)
    service.update_key(db, proj, br, key, changes, _actor(p))
    if archived is not None:
        service.archive_key(db, proj, br, key, _actor(p), on=archived)
    return _key_out(db, proj, br, key)


@router.get("/strings/projects/{project_id}/keys/{key_id}/history")
def key_history(project_id: str, key_id: str, p: Reader, db: DB, lang: str | None = None) -> dict[str, Any]:
    proj = service.get_project(db, p.org_id, project_id)
    key = service.get_key(db, proj, key_id)
    return {"items": service.key_history(db, proj, key, service.norm_locale(lang) if lang else None)}


@router.put("/strings/projects/{project_id}/keys/{key_id}/translations/{lang}")
def put_translation(
    project_id: str,
    key_id: str,
    lang: str,
    body: TranslationIn,
    p: Writer,
    db: DB,
    branch: str | None = None,
) -> dict[str, Any]:
    proj = service.get_project(db, p.org_id, project_id)
    br = service.get_branch(db, proj, branch)
    key = service.get_key(db, proj, key_id)
    lang = service.norm_locale(lang)
    if lang not in service.project_langs(proj):
        raise Invalid(f"{lang} is not a language of this project")
    value: Any = body.value if key.kind == "string" else body.forms
    if value is None or value == "" or value == {}:
        raise Invalid("value (string keys) or forms (plural and array keys) is required")
    is_base = lang == proj.base_lang
    s = service.settings_of(proj)
    issues: list[dict[str, Any]] = []
    if not is_base:
        base = service.value_of(
            service.effective(db, br, [key.id], [proj.base_lang]).get((key.id, proj.base_lang))
        )
        issues = check_value(key, base, value, lang, style=s["placeholder_style"], rules=s["plural_rules"])
    blocked = any(i["blocking"] for i in issues)
    state = "approved" if is_base else (body.state or "reviewed")
    service.write_translation(
        db,
        proj,
        br,
        key,
        lang,
        value,
        state=state,
        origin="human",
        event="edited",
        actor_type="human",
        actor_id=_actor(p),
        qa=issues,
        blocked=blocked,
        needs_review=blocked,
    )
    if not is_base and not blocked and state in ("reviewed", "approved"):
        translate.store_tm(db, proj, key, lang, base, value, origin="review")
    return _key_out(db, proj, br, key)


@router.delete("/strings/projects/{project_id}/keys/{key_id}/translations/{lang}")
def clear_translation(
    project_id: str, key_id: str, lang: str, p: Writer, db: DB, branch: str | None = None
) -> dict[str, Any]:
    proj = service.get_project(db, p.org_id, project_id)
    br = service.get_branch(db, proj, branch)
    key = service.get_key(db, proj, key_id)
    lang = service.norm_locale(lang)
    if lang == proj.base_lang:
        raise Invalid("the base-language text cannot be cleared; archive the key instead")
    service.write_translation(
        db,
        proj,
        br,
        key,
        lang,
        None,
        state="untranslated",
        origin="human",
        event="cleared",
        actor_id=_actor(p),
        qa=[],
        blocked=False,
        needs_review=False,
    )
    return _key_out(db, proj, br, key)


@router.post("/strings/projects/{project_id}/keys/{key_id}/translations/{lang}/suggest")
def suggest(
    project_id: str, key_id: str, lang: str, p: Writer, db: DB, branch: str | None = None
) -> dict[str, Any]:
    """Machine-translate one empty translation now (TM, engine, QA, QE), like a batch of one."""
    proj = service.get_project(db, p.org_id, project_id)
    br = service.get_branch(db, proj, branch)
    service.writable(br)
    key = service.get_key(db, proj, key_id)
    lang = service.norm_locale(lang)
    if lang not in proj.target_langs:
        raise Invalid(f"{lang} is not a target language of this project")
    outcome = translate.translate_one(db, proj, br, key, lang)
    return {"outcome": outcome, "key": _key_out(db, proj, br, key)}


# ------------------------------------------------------------------ translate and bulk


@router.post("/strings/projects/{project_id}/translate", status_code=202)
def translate_missing(project_id: str, body: TranslateIn, p: Writer, db: DB) -> dict[str, Any]:
    proj = service.get_project(db, p.org_id, project_id)
    br = service.get_branch(db, proj, body.branch)
    batch = translate.start_batch(
        db, proj, br, body.langs, mode=body.mode, key_ids=body.key_ids, actor=_actor(p)
    )
    return translate.batch_view(batch)


@router.get("/strings/projects/{project_id}/batches")
def list_batches(project_id: str, p: Reader, db: DB, pg: Paging) -> dict[str, Any]:
    from sqlalchemy import select

    proj = service.get_project(db, p.org_id, project_id)
    rows = list(
        db.execute(
            select(StringBatch)
            .where(StringBatch.project_id == proj.id)
            .order_by(StringBatch.created_at.desc())
            .offset(pg.offset)
            .limit(pg.limit + 1)
        ).scalars()
    )
    return listing([translate.batch_view(b) for b in rows], pg)


@router.get("/strings/projects/{project_id}/batches/{batch_id}")
def get_batch(project_id: str, batch_id: str, p: Reader, db: DB) -> dict[str, Any]:
    proj = service.get_project(db, p.org_id, project_id)
    b = db.get(StringBatch, batch_id)
    if b is None or b.project_id != proj.id:
        raise NotFound("batch not found")
    return translate.batch_view(b)


@router.post("/strings/projects/{project_id}/bulk")
def bulk(project_id: str, body: BulkIn, p: Writer, db: DB) -> dict[str, Any]:
    proj = service.get_project(db, p.org_id, project_id)
    br = service.get_branch(db, proj, body.branch)
    if body.action in ("pretranslate_tm", "translate"):
        mode = "tm_only" if body.action == "pretranslate_tm" else "translate"
        batch = translate.start_batch(
            db, proj, br, body.langs, mode=mode, key_ids=body.key_ids, actor=_actor(p)
        )
        return {"action": body.action, "batch": translate.batch_view(batch)}
    service.writable(br)
    keys = service.visible_keys(db, proj, br, include_archived=True)
    if body.key_ids is not None:
        wanted = set(body.key_ids)
        keys = [k for k in keys if k.id in wanted]
    langs = [service.norm_locale(lg) for lg in (body.langs or proj.target_langs)]
    actor = _actor(p)
    changed = 0
    if body.action in ("archive", "unarchive"):
        for k in keys:
            if (k.archived_at is None) == (body.action == "archive"):
                service.archive_key(db, proj, br, k, actor, on=body.action == "archive")
                changed += 1
    elif body.action in ("tag", "untag"):
        if not body.tag:
            raise Invalid("tag is required")
        for k in keys:
            tags = set(k.tags or [])
            new = tags | {body.tag} if body.action == "tag" else tags - {body.tag}
            if new != tags:
                service.update_key(db, proj, br, k, {"tags": sorted(new)}, actor)
                changed += 1
    else:
        eff = service.effective(db, br, [k.id for k in keys], [proj.base_lang, *langs])
        for k in keys:
            for lg in langs:
                if lg == proj.base_lang:
                    continue
                tr = eff.get((k.id, lg))
                if not service.has_value(tr):
                    continue
                assert tr is not None
                if body.action == "approve":
                    if tr.blocked or tr.state == "approved":
                        continue
                    service.write_translation(
                        db,
                        proj,
                        br,
                        k,
                        lg,
                        service.value_of(tr),
                        state="approved",
                        origin=tr.origin or "human",
                        event="approved",
                        actor_id=actor,
                        needs_review=False,
                    )
                    translate.store_tm(
                        db,
                        proj,
                        k,
                        lg,
                        service.value_of(eff.get((k.id, proj.base_lang))),
                        service.value_of(tr),
                        origin="review",
                    )
                else:
                    service.write_translation(
                        db,
                        proj,
                        br,
                        k,
                        lg,
                        None,
                        state="untranslated",
                        origin="human",
                        event="cleared",
                        actor_id=actor,
                        qa=[],
                        blocked=False,
                        needs_review=False,
                    )
                changed += 1
    return {"action": body.action, "changed": changed}


# ------------------------------------------------------------------ branches


@router.get("/strings/projects/{project_id}/branches")
def list_branches(project_id: str, p: Reader, db: DB) -> dict[str, Any]:
    proj = service.get_project(db, p.org_id, project_id)
    return {"items": [service.branch_view(db, b) for b in service.list_branches(db, proj)]}


@router.post("/strings/projects/{project_id}/branches", status_code=201)
def create_branch(project_id: str, body: BranchIn, p: Writer, db: DB) -> dict[str, Any]:
    proj = service.get_project(db, p.org_id, project_id)
    return service.branch_view(db, service.create_branch(db, proj, body.name, _actor(p)))


@router.get("/strings/projects/{project_id}/branches/{branch}/merge-preview")
def merge_preview(project_id: str, branch: str, p: Reader, db: DB) -> dict[str, Any]:
    proj = service.get_project(db, p.org_id, project_id)
    br = service.get_branch(db, proj, branch)
    conflicts = service.merge_preview(db, proj, br)
    return {"branch": service.branch_view(db, br), "conflicts": [service.conflict_view(c) for c in conflicts]}


@router.post("/strings/projects/{project_id}/branches/{branch}/merge")
def merge(project_id: str, branch: str, body: MergeIn, p: Writer, db: DB) -> dict[str, Any]:
    proj = service.get_project(db, p.org_id, project_id)
    br = service.get_branch(db, proj, branch)
    result = service.merge_branch(db, proj, br, _actor(p), body.resolutions)
    return {**result, "branch": service.branch_view(db, br)}


@router.delete("/strings/projects/{project_id}/branches/{branch}", status_code=204)
def delete_branch(project_id: str, branch: str, p: Writer, db: DB) -> Response:
    proj = service.get_project(db, p.org_id, project_id)
    br = service.get_branch(db, proj, branch)
    if br.is_main:
        raise Invalid("main cannot be deleted")
    db.delete(br)  # branch rows and branch-created keys go with it (ON DELETE CASCADE)
    db.flush()
    return Response(status_code=204)


# ------------------------------------------------------------------ releases


@router.get("/strings/projects/{project_id}/releases")
def list_releases(project_id: str, p: Reader, db: DB, pg: Paging) -> dict[str, Any]:
    proj = service.get_project(db, p.org_id, project_id)
    rows = releases.list_releases(db, proj, pg.offset, pg.limit)
    return listing([releases.release_view(proj, r) for r in rows], pg)


@router.post("/strings/projects/{project_id}/releases", status_code=201)
def create_release(
    project_id: str,
    body: ReleaseIn,
    p: Writer,
    db: DB,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Any:
    from arbiter.platform.permissions import has_permission

    if body.publish and not has_permission(p, "strings.publish"):
        from arbiter.errors import Forbidden

        raise Forbidden("missing permission strings.publish")
    proj = service.get_project(db, p.org_id, project_id)
    payload = {"project": project_id, **body.model_dump()}
    replay = idempotent_replay(db, p, "strings.release", idempotency_key, payload)
    if replay is not None:
        return replay
    br = service.get_branch(db, proj, body.branch)
    rel = releases.create_release(
        db,
        proj,
        br,
        version_label=body.version_label,
        langs=body.langs,
        extra_formats=body.formats,
        publish=body.publish,
        actor=_actor(p),
    )
    out = releases.release_view(proj, rel)
    idempotent_store(db, p, "strings.release", idempotency_key, payload, 201, out)
    return out


@router.get("/strings/projects/{project_id}/releases/{release}")
def get_release(project_id: str, release: str, p: Reader, db: DB) -> dict[str, Any]:
    proj = service.get_project(db, p.org_id, project_id)
    return releases.release_view(proj, releases.get_release(db, proj, release))


@router.post("/strings/projects/{project_id}/releases/{release}/publish")
def publish_release(project_id: str, release: str, p: Publisher, db: DB) -> dict[str, Any]:
    proj = service.get_project(db, p.org_id, project_id)
    rel = releases.publish_release(db, proj, releases.get_release(db, proj, release))
    return releases.release_view(proj, rel)


@router.get("/strings/projects/{project_id}/releases/{release}/files/{lang}/{fmt}")
def release_file(project_id: str, release: str, lang: str, fmt: str, p: Reader, db: DB) -> Response:
    proj = service.get_project(db, p.org_id, project_id)
    rel = releases.get_release(db, proj, release)
    data, ctype, filename = releases.release_file(rel, lang, fmt)
    return Response(
        data, media_type=ctype, headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.post("/strings/projects/{project_id}/distribution-token")
def distribution_token(project_id: str, p: Publisher, db: DB) -> dict[str, Any]:
    """Make the project private and return a new OTA distribution token (shown once)."""
    proj = service.get_project(db, p.org_id, project_id)
    return {"token": releases.new_distribution_token(db, proj), "private": True}


# ------------------------------------------------------------------ CI: push and pull


@router.post("/strings/projects/{project_id}/push")
def push(
    project_id: str,
    p: Writer,
    db: DB,
    file: Annotated[UploadFile, File()],
    format: Annotated[str | None, Form()] = None,
    lang: Annotated[str | None, Form()] = None,
    branch: Annotated[str | None, Form()] = None,
    namespace: Annotated[str, Form(max_length=200)] = "",
    create_keys: Annotated[bool | None, Form()] = None,
    update_changed: Annotated[bool, Form()] = True,
    archive_missing: Annotated[bool, Form()] = False,
    tag: Annotated[str | None, Form(max_length=100)] = None,
    state: Annotated[Literal["machine", "reviewed", "approved"], Form()] = "reviewed",
) -> dict[str, Any]:
    proj = service.get_project(db, p.org_id, project_id)
    br = service.get_branch(db, proj, branch)
    data = file.file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise Invalid("the file is larger than 20 MB")
    lang_n = service.norm_locale(lang) if lang else proj.base_lang
    try:
        fmt = format or formats.detect(file.filename or "", data)
        doc = formats.parse(fmt, data, lang_n, proj.base_lang)
    except StringsFormatError as e:
        raise _fmt_error(e) from None
    opts = service.ImportOptions(
        lang=lang_n,
        namespace=namespace,
        create_keys=create_keys if create_keys is not None else lang_n == proj.base_lang,
        update_changed=update_changed,
        archive_missing=archive_missing,
        tag=tag or None,
        state=state,
    )
    result = service.import_doc(db, proj, br, doc, opts, _actor(p))
    return {"format": fmt, "lang": lang_n, "branch": br.name, "keys_in_file": len(doc.rows), **result}


@router.get("/strings/projects/{project_id}/pull")
def pull(
    project_id: str,
    p: Reader,
    db: DB,
    lang: str | None = None,
    format: str | None = None,
    branch: str | None = None,
    namespace: str | None = None,
    min_state: Literal["machine", "reviewed", "approved"] = "machine",
    fallback: bool = False,
    include_blocked: bool = False,
) -> Response:
    proj = service.get_project(db, p.org_id, project_id)
    br = service.get_branch(db, proj, branch)
    fmt = format or service.settings_of(proj)["default_format"]
    try:
        spec = formats.get(fmt)
    except StringsFormatError as e:
        raise _fmt_error(e) from None
    lang_n = service.norm_locale(lang) if lang else proj.base_lang
    if lang_n not in service.project_langs(proj):
        raise Invalid(f"{lang_n} is not a language of this project")
    langs = service.project_langs(proj) if spec.multilingual and not lang else [lang_n]
    doc = service.export_doc(
        db,
        proj,
        br,
        langs,
        namespace=namespace,
        min_state=min_state,
        include_blocked=include_blocked,
        fallback_to_base=fallback,
    )
    if not spec.multilingual:
        doc.langs = []
    data = spec.render(doc, lang_n)
    name = f"{'all' if spec.multilingual and not lang else lang_n}.{spec.extension}"
    return Response(
        data, media_type=spec.content_type, headers={"Content-Disposition": f'attachment; filename="{name}"'}
    )


# ------------------------------------------------------------------ public OTA (no auth)

VERSIONED_CACHE = "public, max-age=31536000, immutable"
LATEST_CACHE = "public, max-age=60, stale-while-revalidate=300"


def _ota_response(request: Request, body: bytes, etag: str, cache: str, private: bool) -> Response:
    if private:
        cache = cache.replace("public", "private")
    headers = {
        "ETag": f'"{etag}"',
        "Cache-Control": cache,
        "Access-Control-Allow-Origin": "*",
        "Vary": "Accept-Encoding" + (", X-Distribution-Token" if private else ""),
        "X-Content-Type-Options": "nosniff",
    }
    inm = request.headers.get("if-none-match", "")
    if etag and any(t.strip().strip('"').removeprefix("W/").strip('"') == etag for t in inm.split(",")):
        return Response(status_code=304, headers=headers)
    return Response(body, media_type="application/json", headers=headers)


@public_router.get("/ota/{public_id}/{ref}/{name}", include_in_schema=True)
def ota(
    public_id: str,
    ref: str,
    name: str,
    request: Request,
    db: DB,
    token: str | None = None,
    x_distribution_token: Annotated[str | None, Header()] = None,
) -> Response:
    proj, rel = releases.resolve_public(db, public_id, ref)
    private = bool((proj.settings or {}).get("private"))
    if not releases.token_ok(proj, x_distribution_token or token):
        raise NotFound("not found")  # never confirm that a private project exists
    cache = LATEST_CACHE if ref == "latest" else VERSIONED_CACHE
    if name == "manifest.json":
        body = releases.canonical(
            {
                "project": proj.public_id,
                "release": rel.id,
                "version_label": rel.version_label,
                "published_at": rel.published_at.isoformat() if rel.published_at else None,
                "content_hash": rel.content_hash,
                "base_lang": proj.base_lang,
                "langs": {
                    lang: {
                        "url": releases.ota_urls(proj, rel)["langs"][lang]["versioned"],
                        "sha256": (rel.bundles or {}).get(lang, {}).get("json", {}).get("sha256"),
                    }
                    for lang in rel.langs
                },
            }
        )
        return _ota_response(request, body, rel.content_hash, cache, private)
    if not name.endswith(".json"):
        raise NotFound("not found")
    lang = name[: -len(".json")]
    entry = (rel.bundles or {}).get(lang, {}).get("json")
    if entry is None:
        try:
            lang = service.norm_locale(lang)
        except Invalid:
            raise NotFound("not found") from None
        entry = (rel.bundles or {}).get(lang, {}).get("json")
    if entry is None:
        raise NotFound("not found")
    from arbiter import storage

    return _ota_response(request, storage.get(entry["key"]), entry["sha256"], cache, private)
