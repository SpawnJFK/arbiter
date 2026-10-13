"""Software strings: projects, keys, translations, branches, import (push) and export (pull).

Rules (ids referenced from tests and docs):
  R-STR-01  Every query is scoped by the project's org; another org's project is a 404.
  R-STR-02  A translation write bumps `version` and appends a string_history row (append-only).
  R-STR-03  Changing a base-language value drops reviewed/approved translations of that key
            back to `machine` (they were checked against the old source) with event
            source_changed.
  R-STR-04  Copy-on-write branches: writing in a branch creates a branch row that records the
            main row's version (base_version); reads prefer the branch row (D-051).
  R-STR-05  Merge applies branch rows whose main row is unchanged since the copy; a main row
            that moved on is a conflict, listed for resolution (keep branch / keep main).
  R-STR-06  Import never overwrites base-language text from a bilingual file (PO, XLIFF):
            translators deliver targets, developers own the source.
  R-STR-07  Regulated organizations cannot use the auto or ai_review tiers (R-SEG-12).
  R-STR-08  A translation with a blocking QA issue (placeholder changed, broken ICU, plural
            form missing, too long) is `blocked` and never shipped in a release.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arbiter.errors import Conflict, Invalid, NotFound
from arbiter.models import (
    Organization,
    StringBranch,
    StringHistory,
    StringKey,
    StringProject,
    StringTranslation,
    utcnow,
)
from arbiter.strings import placeholders as ph
from arbiter.strings import plurals
from arbiter.strings.formats.base import Doc, KeyRow, Value

STATES = ("untranslated", "machine", "reviewed", "approved")
STATE_RANK = {s: i for i, s in enumerate(STATES)}
TIERS = ("auto", "ai_review", "hybrid", "full")
KINDS = ("string", "plural", "array")
PLATFORMS = ("web", "ios", "android", "flutter", "backend", "desktop", "other")
DEFAULT_SETTINGS: dict[str, Any] = {
    "placeholder_style": "auto",
    "plural_rules": {},
    "human_review": False,
    "release_min_state": "machine",
    "fallback_to_base": True,
    "private": False,
    "default_format": "json",
    "engine": None,
}
MAIN = "main"
_LOCALE = re.compile(r"^([A-Za-z]{2,3})(?:[-_]([A-Za-z]{4}))?(?:[-_]([A-Za-z]{2}|\d{3}))?$")
_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")


def norm_locale(value: str) -> str:
    """BCP-47 language[-Script][-REGION]: "pt_br" -> "pt-BR", "zh-hans" -> "zh-Hans"."""
    m = _LOCALE.match((value or "").strip())
    if not m:
        raise Invalid(f"language must be a BCP-47 tag like en, de, pt-BR or zh-Hans, got {value!r}")
    lang, script, region = m.groups()
    out = lang.lower()
    if script:
        out += "-" + script.title()
    if region:
        out += "-" + region.upper()
    return out


def settings_of(proj: StringProject) -> dict[str, Any]:
    return {**DEFAULT_SETTINGS, **(proj.settings or {})}


def is_valid_value(kind: str, value: Value | None) -> bool:
    if kind == "string":
        return isinstance(value, str)
    return isinstance(value, dict) and all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    )


# ================================================================== projects


def _check_tier(org: Organization, tier: str) -> None:
    if tier not in TIERS:
        raise Invalid(f"tier must be one of {', '.join(TIERS)}")
    if org.regulated and tier in ("auto", "ai_review"):
        raise Invalid("regulated organizations need a human reviewer: use the hybrid or full tier (R-STR-07)")


def create_project(
    db: Session,
    org: Organization,
    *,
    name: str,
    base_lang: str,
    target_langs: Sequence[str],
    platforms: Sequence[str] = (),
    tier: str | None = None,
    settings: dict[str, Any] | None = None,
    actor: str | None = None,
) -> StringProject:
    base = norm_locale(base_lang)
    targets = list(dict.fromkeys(norm_locale(t) for t in target_langs))
    if base in targets:
        raise Invalid("the base language cannot also be a target language")
    bad = [p for p in platforms if p not in PLATFORMS]
    if bad:
        raise Invalid(f"unknown platform(s): {', '.join(bad)}")
    tier = tier or (org.default_tier if org.default_tier in TIERS else "hybrid")
    _check_tier(org, tier)
    proj = StringProject(
        org_id=org.id,
        name=name.strip(),
        public_id="sp" + secrets.token_hex(12),
        base_lang=base,
        target_langs=targets,
        platforms=list(dict.fromkeys(platforms)),
        tier=tier,
        settings=_clean_settings(settings or {}),
        created_by=actor,
    )
    db.add(proj)
    db.flush()
    db.add(StringBranch(project_id=proj.id, name=MAIN, is_main=True, created_by=actor))
    db.flush()
    return proj


def _clean_settings(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in raw.items():
        if k not in DEFAULT_SETTINGS:
            raise Invalid(f"unknown setting {k!r}")
        out[k] = v
    if "placeholder_style" in out and out["placeholder_style"] not in ph.STYLES:
        raise Invalid(f"placeholder_style must be one of {', '.join(ph.STYLES)}")
    if "release_min_state" in out and out["release_min_state"] not in STATES[1:]:
        raise Invalid("release_min_state must be machine, reviewed or approved")
    rules = out.get("plural_rules")
    bad_rules = rules is not None and (
        not isinstance(rules, dict)
        or any(not isinstance(v, list) or any(c not in plurals.ORDER for c in v) for v in rules.values())
    )
    if bad_rules:
        raise Invalid("plural_rules maps a language to a list of CLDR categories")
    from arbiter.strings import formats

    if "default_format" in out and out["default_format"] not in formats.FORMATS:
        raise Invalid(f"default_format must be one of {', '.join(formats.FORMATS)}")
    return out


def update_project(
    db: Session, org: Organization, proj: StringProject, changes: dict[str, Any]
) -> StringProject:
    if "name" in changes and changes["name"]:
        proj.name = str(changes["name"]).strip()
    if "target_langs" in changes and changes["target_langs"] is not None:
        targets = list(dict.fromkeys(norm_locale(t) for t in changes["target_langs"]))
        if proj.base_lang in targets:
            raise Invalid("the base language cannot also be a target language")
        proj.target_langs = targets
    if "platforms" in changes and changes["platforms"] is not None:
        bad = [p for p in changes["platforms"] if p not in PLATFORMS]
        if bad:
            raise Invalid(f"unknown platform(s): {', '.join(bad)}")
        proj.platforms = list(dict.fromkeys(changes["platforms"]))
    if changes.get("tier"):
        _check_tier(org, changes["tier"])
        proj.tier = changes["tier"]
    if changes.get("settings"):
        merged = {**(proj.settings or {}), **_clean_settings(changes["settings"])}
        proj.settings = merged
    db.flush()
    return proj


def get_project(db: Session, org_id: str, project_id: str) -> StringProject:
    proj = db.get(StringProject, project_id)
    if proj is None or proj.org_id != org_id or proj.archived_at is not None:
        raise NotFound("string project not found")  # R-STR-01: another org gets 404
    return proj


def list_projects(db: Session, org_id: str, offset: int, limit: int) -> list[StringProject]:
    stmt = (
        select(StringProject)
        .where(StringProject.org_id == org_id, StringProject.archived_at.is_(None))
        .order_by(StringProject.created_at.desc())
        .offset(offset)
        .limit(limit + 1)
    )
    return list(db.execute(stmt).scalars())


def project_langs(proj: StringProject) -> list[str]:
    return [proj.base_lang, *proj.target_langs]


def project_stats(db: Session, proj: StringProject) -> dict[str, Any]:
    branch = main_branch(db, proj)
    keys = visible_keys(db, proj, branch)
    active = [k for k in keys if k.archived_at is None and k.translatable]
    eff = effective(db, branch, [k.id for k in active], project_langs(proj))
    per_lang: dict[str, dict[str, int]] = {}
    for lang in project_langs(proj):
        counts = dict.fromkeys(STATES, 0)
        counts["blocked"] = 0
        for k in active:
            tr = eff.get((k.id, lang))
            state = tr.state if tr is not None and has_value(tr) else "untranslated"
            counts[state] += 1
            if tr is not None and tr.blocked:
                counts["blocked"] += 1
        done = counts["machine"] + counts["reviewed"] + counts["approved"]
        counts["progress"] = round(100 * done / len(active)) if active else 0
        per_lang[lang] = counts
    return {"keys": len(active), "archived": len(keys) - len(active), "languages": per_lang}


# ================================================================== branches


def main_branch(db: Session, proj: StringProject) -> StringBranch:
    b = db.execute(
        select(StringBranch).where(StringBranch.project_id == proj.id, StringBranch.is_main.is_(True))
    ).scalar_one_or_none()
    if b is None:  # defensive: projects always get one at creation
        b = StringBranch(project_id=proj.id, name=MAIN, is_main=True)
        db.add(b)
        db.flush()
    return b


def get_branch(db: Session, proj: StringProject, ref: str | None) -> StringBranch:
    """By name or id; None / "" / "main" = main. Merged branches are read-only (Conflict on write)."""
    if not ref or ref == MAIN:
        return main_branch(db, proj)
    b = db.execute(
        select(StringBranch).where(
            StringBranch.project_id == proj.id, (StringBranch.name == ref) | (StringBranch.id == ref)
        )
    ).scalar_one_or_none()
    if b is None:
        raise NotFound(f"branch {ref!r} not found")
    return b


def writable(branch: StringBranch) -> None:
    if branch.merged_at is not None:
        raise Conflict(f"branch {branch.name!r} was merged and is read-only")


def create_branch(db: Session, proj: StringProject, name: str, actor: str | None) -> StringBranch:
    name = name.strip()
    if not _BRANCH.match(name) or name == MAIN:
        raise Invalid("branch names use letters, digits, '.', '_', '-', '/' and cannot be 'main'")
    if db.execute(
        select(StringBranch.id).where(StringBranch.project_id == proj.id, StringBranch.name == name)
    ).first():
        raise Conflict(f"branch {name!r} already exists")
    main = main_branch(db, proj)
    b = StringBranch(project_id=proj.id, name=name, from_branch_id=main.id, created_by=actor)
    db.add(b)
    db.flush()
    return b


def list_branches(db: Session, proj: StringProject) -> list[StringBranch]:
    return list(
        db.execute(
            select(StringBranch)
            .where(StringBranch.project_id == proj.id)
            .order_by(StringBranch.is_main.desc(), StringBranch.created_at)
        ).scalars()
    )


def _chain(db: Session, branch: StringBranch) -> list[str]:
    """Branch ids to read through, most specific first."""
    if branch.is_main or branch.from_branch_id is None:
        return [branch.id]
    return [branch.id, branch.from_branch_id]


# ================================================================== keys and translations


def visible_keys(
    db: Session, proj: StringProject, branch: StringBranch, *, include_archived: bool = True
) -> list[StringKey]:
    stmt = select(StringKey).where(
        StringKey.project_id == proj.id, StringKey.branch_id.in_(_chain(db, branch))
    )
    if not include_archived:
        stmt = stmt.where(StringKey.archived_at.is_(None))
    return list(db.execute(stmt.order_by(StringKey.namespace, StringKey.name)).scalars())


def find_key(
    db: Session, proj: StringProject, branch: StringBranch, namespace: str, name: str
) -> StringKey | None:
    k = db.execute(
        select(StringKey).where(
            StringKey.project_id == proj.id, StringKey.namespace == namespace, StringKey.name == name
        )
    ).scalar_one_or_none()
    if k is None:
        return None
    if k.branch_id not in _chain(db, branch):
        raise Conflict(f"key {name!r} exists in another branch; merge that branch first")
    return k


def get_key(db: Session, proj: StringProject, key_id: str) -> StringKey:
    k = db.get(StringKey, key_id)
    if k is None or k.project_id != proj.id:
        raise NotFound("key not found")
    return k


def effective(
    db: Session, branch: StringBranch, key_ids: Iterable[str], langs: Iterable[str]
) -> dict[tuple[str, str], StringTranslation]:
    """(key_id, lang) -> the translation row a reader in `branch` sees (branch row wins)."""
    ids = list(key_ids)
    langs = list(langs)
    if not ids or not langs:
        return {}
    chain = _chain(db, branch)
    out: dict[tuple[str, str], StringTranslation] = {}
    rank: dict[tuple[str, str], int] = {}
    for start in range(0, len(ids), 5000):
        rows = db.execute(
            select(StringTranslation).where(
                StringTranslation.key_id.in_(ids[start : start + 5000]),
                StringTranslation.branch_id.in_(chain),
                StringTranslation.lang.in_(langs),
            )
        ).scalars()
        for tr in rows:
            k = (tr.key_id, tr.lang)
            r = chain.index(tr.branch_id)
            if k not in rank or r < rank[k]:
                out[k], rank[k] = tr, r
    return out


def has_value(tr: StringTranslation | None) -> bool:
    if tr is None:
        return False
    if tr.forms is not None:
        return any(v for v in tr.forms.values())
    return bool(tr.value)


def value_of(tr: StringTranslation | None) -> Value | None:
    if tr is None or not has_value(tr):
        return None
    return dict(tr.forms) if tr.forms is not None else tr.value


def history(
    db: Session,
    proj: StringProject,
    key: StringKey,
    branch: StringBranch,
    lang: str,
    event: str,
    *,
    tr: StringTranslation | None = None,
    actor_type: str = "system",
    actor_id: str = "",
    **data: Any,
) -> None:
    db.add(
        StringHistory(
            org_id=proj.org_id,
            project_id=proj.id,
            key_id=key.id,
            branch_id=branch.id,
            lang=lang,
            event=event,
            version=tr.version if tr is not None else 0,
            value=tr.value if tr is not None else "",
            forms=dict(tr.forms) if tr is not None and tr.forms is not None else None,
            state=tr.state if tr is not None else "",
            actor_type=actor_type,
            actor_id=actor_id or "",
            data=_jsonable(data),
        )
    )


def _jsonable(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(a): _jsonable(b) for a, b in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


@dataclass
class WriteResult:
    tr: StringTranslation
    changed: bool


def write_translation(
    db: Session,
    proj: StringProject,
    branch: StringBranch,
    key: StringKey,
    lang: str,
    value: Value | None,
    *,
    state: str,
    origin: str,
    event: str,
    actor_type: str = "human",
    actor_id: str = "",
    engine: str | None = None,
    qe_score: float | None = None,
    qa: list[dict[str, Any]] | None = None,
    blocked: bool | None = None,
    needs_review: bool | None = None,
    **data: Any,
) -> WriteResult:
    """Set one translation (R-STR-02/03/04). value None clears it (state untranslated)."""
    writable(branch)
    if state not in STATES:
        raise Invalid(f"state must be one of {', '.join(STATES)}")
    if value is not None and not is_valid_value(key.kind, value):
        raise Invalid(f"value does not match the key kind {key.kind!r}")
    chain = _chain(db, branch)
    rows = {
        tr.branch_id: tr
        for tr in db.execute(
            select(StringTranslation).where(
                StringTranslation.key_id == key.id,
                StringTranslation.lang == lang,
                StringTranslation.branch_id.in_(chain),
            )
        ).scalars()
    }
    tr = rows.get(branch.id)
    new_value = value if isinstance(value, str) else ""
    new_forms = dict(value) if isinstance(value, dict) else None
    if value is None:
        state = "untranslated"
    old_value = value_of(tr) if tr is not None else value_of(rows.get(chain[-1])) if len(chain) > 1 else None
    if tr is None:
        base = rows.get(chain[-1]) if len(chain) > 1 else None
        tr = StringTranslation(
            key_id=key.id,
            branch_id=branch.id,
            lang=lang,
            version=0,
            base_version=(base.version if base is not None else 0) if not branch.is_main else None,
            qa=[],
            blocked=False,
            needs_review=False,
        )
        if base is not None:  # copy the inherited row so untouched fields carry over
            tr.qe_score, tr.engine, tr.origin = base.qe_score, base.engine, base.origin
        db.add(tr)
    elif (
        tr.value == new_value
        and tr.forms == new_forms
        and tr.state == state
        and (qa is None or qa == (tr.qa or []))
        and (blocked is None or blocked == tr.blocked)
        and (needs_review is None or needs_review == tr.needs_review)
    ):
        return WriteResult(tr, False)
    tr.value = new_value
    tr.forms = new_forms
    tr.state = state
    tr.origin = origin
    tr.engine = engine if engine is not None else (tr.engine if origin in ("mt", "tm") else None)
    tr.qe_score = qe_score if qe_score is not None else (tr.qe_score if origin == "mt" else None)
    if qa is not None:
        tr.qa = qa
    if blocked is not None:
        tr.blocked = blocked
    if needs_review is not None:
        tr.needs_review = needs_review
    tr.updated_by = actor_id or None
    tr.version = (tr.version or 0) + 1
    tr.updated_at = utcnow()
    db.flush()
    history(db, proj, key, branch, lang, event, tr=tr, actor_type=actor_type, actor_id=actor_id, **data)
    if lang == proj.base_lang and old_value is not None and old_value != value:
        _source_changed(db, proj, branch, key, actor_id)
    return WriteResult(tr, True)


def _source_changed(
    db: Session, proj: StringProject, branch: StringBranch, key: StringKey, actor: str
) -> None:
    """R-STR-03: translations checked against the old source go back to machine."""
    eff = effective(db, branch, [key.id], proj.target_langs)
    for (_, lang), tr in eff.items():
        if tr.state in ("reviewed", "approved") and has_value(tr):
            write_translation(
                db,
                proj,
                branch,
                key,
                lang,
                value_of(tr),
                state="machine",
                origin=tr.origin or "import",
                event="source_changed",
                actor_type="system",
                actor_id=actor,
                needs_review=True,
            )


def create_key(
    db: Session,
    proj: StringProject,
    branch: StringBranch,
    *,
    name: str,
    namespace: str = "",
    kind: str = "string",
    description: str = "",
    max_length: int | None = None,
    tags: Sequence[str] = (),
    screenshot_url: str | None = None,
    translatable: bool = True,
    meta: dict[str, Any] | None = None,
    base_value: Value | None = None,
    actor: str = "",
    actor_type: str = "human",
) -> StringKey:
    writable(branch)
    name = name.strip()
    if not name:
        raise Invalid("key name is required")
    if kind not in KINDS:
        raise Invalid(f"kind must be one of {', '.join(KINDS)}")
    if find_key(db, proj, branch, namespace, name) is not None:
        raise Conflict(f"key {name!r} already exists" + (f" in namespace {namespace!r}" if namespace else ""))
    key = StringKey(
        project_id=proj.id,
        branch_id=branch.id,
        namespace=namespace,
        name=name,
        kind=kind,
        description=description or "",
        max_length=max_length,
        tags=sorted(set(tags)),
        screenshot_url=screenshot_url,
        translatable=translatable,
        meta=meta or {},
    )
    db.add(key)
    db.flush()
    history(db, proj, key, branch, "", "created", actor_type=actor_type, actor_id=actor, name=name)
    if base_value is not None:
        write_translation(
            db,
            proj,
            branch,
            key,
            proj.base_lang,
            base_value,
            state="approved",
            origin="human" if actor_type == "human" else "import",
            event="edited",
            actor_type=actor_type,
            actor_id=actor,
        )
    return key


KEY_FIELDS = (
    "description",
    "max_length",
    "tags",
    "screenshot_url",
    "translatable",
    "kind",
    "namespace",
    "name",
)


def update_key(
    db: Session,
    proj: StringProject,
    branch: StringBranch,
    key: StringKey,
    changes: dict[str, Any],
    actor: str,
) -> StringKey:
    """Key metadata is shared by every branch (D-051); only creation and values are branch scoped."""
    writable(branch)
    changed: dict[str, Any] = {}
    for f in KEY_FIELDS:
        if f not in changes:
            continue
        v = changes[f]
        if f == "kind" and v not in KINDS:
            raise Invalid(f"kind must be one of {', '.join(KINDS)}")
        if f == "tags":
            v = sorted({str(t).strip() for t in (v or []) if str(t).strip()})
        if f in ("name", "namespace"):
            v = str(v or "").strip()
            if f == "name" and not v:
                raise Invalid("key name is required")
        if getattr(key, f) != v:
            changed[f] = v
    if "name" in changed or "namespace" in changed:
        ns, nm = changed.get("namespace", key.namespace), changed.get("name", key.name)
        clash = db.execute(
            select(StringKey.id).where(
                StringKey.project_id == proj.id, StringKey.namespace == ns, StringKey.name == nm
            )
        ).first()
        if clash:
            raise Conflict(f"key {nm!r} already exists")
    if "kind" in changed:
        has_values = db.execute(
            select(func.count()).select_from(StringTranslation).where(StringTranslation.key_id == key.id)
        ).scalar_one()
        if has_values:
            raise Conflict("clear the key's values before changing its kind")
    for f, v in changed.items():
        setattr(key, f, v)
    if changed:
        key.updated_at = utcnow()
        history(db, proj, key, branch, "", "key_updated", actor_type="human", actor_id=actor, changes=changed)
    db.flush()
    return key


def archive_key(
    db: Session, proj: StringProject, branch: StringBranch, key: StringKey, actor: str, *, on: bool
) -> None:
    writable(branch)
    if on and key.archived_at is None:
        key.archived_at = utcnow()
        history(db, proj, key, branch, "", "archived", actor_type="human", actor_id=actor)
    elif not on and key.archived_at is not None:
        key.archived_at = None
        history(db, proj, key, branch, "", "restored", actor_type="human", actor_id=actor)
    db.flush()


def key_history(
    db: Session, proj: StringProject, key: StringKey, lang: str | None, limit: int = 200
) -> list[dict]:
    stmt = select(StringHistory).where(StringHistory.project_id == proj.id, StringHistory.key_id == key.id)
    if lang:
        stmt = stmt.where(StringHistory.lang.in_([lang, ""]))
    rows = db.execute(stmt.order_by(StringHistory.at.desc(), StringHistory.id.desc()).limit(limit)).scalars()
    return [
        {
            "id": h.id,
            "lang": h.lang,
            "event": h.event,
            "version": h.version,
            "value": h.value,
            "forms": h.forms,
            "state": h.state,
            "actor_type": h.actor_type,
            "actor_id": h.actor_id,
            "branch_id": h.branch_id,
            "data": h.data,
            "at": h.at.isoformat() if h.at else None,
        }
        for h in rows
    ]


# ================================================================== views and search


def translation_view(tr: StringTranslation | None, branch: StringBranch) -> dict[str, Any] | None:
    if tr is None:
        return None
    return {
        "value": tr.value,
        "forms": tr.forms,
        "state": tr.state if has_value(tr) else "untranslated",
        "origin": tr.origin,
        "engine": tr.engine,
        "qe_score": tr.qe_score,
        "qa": tr.qa or [],
        "blocked": tr.blocked,
        "needs_review": tr.needs_review,
        "version": tr.version,
        "updated_by": tr.updated_by,
        "updated_at": tr.updated_at.isoformat() if tr.updated_at else None,
        "branch_local": tr.branch_id == branch.id and not branch.is_main,
    }


def key_view(
    key: StringKey,
    eff: dict[tuple[str, str], StringTranslation],
    langs: Sequence[str],
    branch: StringBranch,
    proj: StringProject,
) -> dict[str, Any]:
    base = value_of(eff.get((key.id, proj.base_lang)))
    style = settings_of(proj)["placeholder_style"]
    sample = base if isinstance(base, str) else " ".join((base or {}).values())
    return {
        "id": key.id,
        "namespace": key.namespace,
        "name": key.name,
        "kind": key.kind,
        "description": key.description,
        "screenshot_url": key.screenshot_url,
        "max_length": key.max_length,
        "tags": key.tags or [],
        "translatable": key.translatable,
        "archived": key.archived_at is not None,
        "branch_local": key.branch_id == branch.id and not branch.is_main,
        "placeholders": [c for c in dict.fromkeys(ph.chips(sample, style)) if not _icu_piece(c)]
        if sample
        else [],
        "plural_forms": {
            lang: list(plurals.categories(lang, settings_of(proj)["plural_rules"])) for lang in langs
        }
        if key.kind == "plural"
        else None,
        "translations": {lang: translation_view(eff.get((key.id, lang)), branch) for lang in langs},
    }


def _icu_piece(code: str) -> bool:
    """Selector and brace codes of an ICU plural/select (not something a translator inserts)."""
    return code.startswith("}") or bool(re.match(r"\{\s*\w+\s*,\s*(plural|select|selectordinal)\s*,", code))


@dataclass
class KeyQuery:
    q: str = ""
    tag: str | None = None
    namespace: str | None = None
    lang: str | None = None
    state: str | None = None  # untranslated | machine | reviewed | approved | blocked | needs_review
    include_archived: bool = False
    langs: list[str] = field(default_factory=list)


def search_keys(
    db: Session, proj: StringProject, branch: StringBranch, query: KeyQuery, offset: int, limit: int
) -> tuple[list[dict[str, Any]], int]:
    keys = visible_keys(db, proj, branch, include_archived=query.include_archived)
    if query.namespace is not None:
        keys = [k for k in keys if k.namespace == query.namespace]
    if query.tag:
        keys = [k for k in keys if query.tag in (k.tags or [])]
    langs = list(dict.fromkeys([proj.base_lang, *(query.langs or proj.target_langs)]))
    if query.lang and query.lang not in langs:
        langs.append(query.lang)
    eff = effective(db, branch, [k.id for k in keys], langs)
    q = query.q.strip().casefold()
    out: list[StringKey] = []
    for k in keys:
        if q:
            hay = [k.name, k.description, k.namespace]
            for lang in langs:
                v = value_of(eff.get((k.id, lang)))
                hay.append(v if isinstance(v, str) else " ".join((v or {}).values()))
            if not any(q in (h or "").casefold() for h in hay):
                continue
        if query.state and query.lang:
            tr = eff.get((k.id, query.lang))
            if query.state == "blocked":
                ok = tr is not None and tr.blocked
            elif query.state == "needs_review":
                ok = tr is not None and tr.needs_review
            else:
                st = tr.state if tr is not None and has_value(tr) else "untranslated"
                ok = st == query.state and (query.state != "untranslated" or k.translatable)
            if not ok:
                continue
        out.append(k)
    total = len(out)
    page = out[offset : offset + limit]
    return [key_view(k, eff, langs, branch, proj) for k in page], total


# ================================================================== branches: merge


@dataclass
class MergeConflict:
    key_id: str
    key: str
    lang: str
    branch_value: Value | None
    main_value: Value | None


def merge_preview(db: Session, proj: StringProject, branch: StringBranch) -> list[MergeConflict]:
    if branch.is_main:
        raise Invalid("main cannot be merged")
    main = main_branch(db, proj)
    rows = list(
        db.execute(select(StringTranslation).where(StringTranslation.branch_id == branch.id)).scalars()
    )
    mains = {
        (t.key_id, t.lang): t
        for t in db.execute(
            select(StringTranslation).where(
                StringTranslation.branch_id == main.id,
                StringTranslation.key_id.in_([r.key_id for r in rows] or [""]),
            )
        ).scalars()
    }
    conflicts: list[MergeConflict] = []
    names = {k.id: k for k in visible_keys(db, proj, branch)}
    for r in rows:
        m = mains.get((r.key_id, r.lang))
        main_version = m.version if m is not None else 0
        if main_version != (r.base_version or 0) and value_of(m) != value_of(r):
            k = names.get(r.key_id)
            conflicts.append(
                MergeConflict(r.key_id, k.name if k else r.key_id, r.lang, value_of(r), value_of(m))
            )
    return conflicts


def merge_branch(
    db: Session,
    proj: StringProject,
    branch: StringBranch,
    actor: str,
    resolutions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """R-STR-05. resolutions: {"<key_id>:<lang>": "branch" | "main"}. Unresolved conflicts -> 409."""
    writable(branch)
    conflicts = merge_preview(db, proj, branch)
    resolutions = resolutions or {}
    open_ = [c for c in conflicts if resolutions.get(f"{c.key_id}:{c.lang}") not in ("branch", "main")]
    if open_:
        raise Conflict(
            "the branch has conflicts with main",
            {"conflicts": [conflict_view(c) for c in open_]},
        )
    skip = {(c.key_id, c.lang) for c in conflicts if resolutions.get(f"{c.key_id}:{c.lang}") == "main"}
    main = main_branch(db, proj)
    applied = 0
    keys = {k.id: k for k in visible_keys(db, proj, branch)}
    moved_keys = 0
    for k in keys.values():
        if k.branch_id == branch.id:
            k.branch_id = main.id
            moved_keys += 1
            history(
                db, proj, k, main, "", "merged", actor_type="human", actor_id=actor, from_branch=branch.name
            )
    db.flush()
    for r in list(
        db.execute(select(StringTranslation).where(StringTranslation.branch_id == branch.id)).scalars()
    ):
        k = keys.get(r.key_id)
        if k is None or (r.key_id, r.lang) in skip:
            continue
        write_translation(
            db,
            proj,
            main,
            k,
            r.lang,
            value_of(r),
            state=r.state if has_value(r) else "untranslated",
            origin=r.origin or "human",
            event="merged",
            actor_type="human",
            actor_id=actor,
            engine=r.engine,
            qe_score=r.qe_score,
            qa=list(r.qa or []),
            blocked=r.blocked,
            needs_review=r.needs_review,
            from_branch=branch.name,
        )
        applied += 1
    branch.merged_at = utcnow()
    branch.merged_by = actor or None
    db.flush()
    return {"applied": applied, "keys_moved": moved_keys, "conflicts_resolved": len(conflicts)}


def conflict_view(c: MergeConflict) -> dict[str, Any]:
    return {
        "key_id": c.key_id,
        "key": c.key,
        "lang": c.lang,
        "branch_value": c.branch_value,
        "main_value": c.main_value,
    }


def branch_view(db: Session, b: StringBranch) -> dict[str, Any]:
    changes = db.execute(
        select(func.count()).select_from(StringTranslation).where(StringTranslation.branch_id == b.id)
    ).scalar_one()
    new_keys = db.execute(
        select(func.count()).select_from(StringKey).where(StringKey.branch_id == b.id)
    ).scalar_one()
    return {
        "id": b.id,
        "name": b.name,
        "is_main": b.is_main,
        "from_branch_id": b.from_branch_id,
        "created_at": b.created_at.isoformat() if b.created_at else None,
        "merged_at": b.merged_at.isoformat() if b.merged_at else None,
        "changes": 0 if b.is_main else changes,
        "new_keys": 0 if b.is_main else new_keys,
    }


# ================================================================== export (pull) and import (push)


def export_doc(
    db: Session,
    proj: StringProject,
    branch: StringBranch,
    langs: Sequence[str],
    *,
    namespace: str | None = None,
    min_state: str = "machine",
    include_blocked: bool = True,
    fallback_to_base: bool = False,
    include_archived: bool = False,
) -> Doc:
    keys = visible_keys(db, proj, branch, include_archived=include_archived)
    if namespace is not None:
        keys = [k for k in keys if k.namespace == namespace]
    want = list(dict.fromkeys([proj.base_lang, *langs]))
    eff = effective(db, branch, [k.id for k in keys], want)
    doc = Doc(base_lang=proj.base_lang, langs=want)
    floor = STATE_RANK.get(min_state, 1)
    for k in keys:
        row = KeyRow(
            key=k.name,
            namespace=k.namespace,
            kind=k.kind,  # type: ignore[arg-type]
            description=k.description,
            max_length=k.max_length,
            translatable=k.translatable,
            tags=list(k.tags or []),
            meta=dict(k.meta or {}),
        )
        base_tr = eff.get((k.id, proj.base_lang))
        for lang in want:
            tr = eff.get((k.id, lang))
            ok = has_value(tr) and (
                lang == proj.base_lang
                or (STATE_RANK.get(tr.state, 0) >= floor and (include_blocked or not tr.blocked))  # type: ignore[union-attr]
            )
            if ok:
                row.values[lang] = value_of(tr)  # type: ignore[assignment]
                row.states[lang] = tr.state  # type: ignore[union-attr]
            elif fallback_to_base and has_value(base_tr) and k.translatable:
                row.values[lang] = value_of(base_tr)  # type: ignore[assignment]
                row.states[lang] = "untranslated"
        if row.values:
            doc.rows.append(row)
    return doc


@dataclass
class ImportOptions:
    lang: str
    namespace: str = ""
    create_keys: bool = True
    update_changed: bool = True
    archive_missing: bool = False
    tag: str | None = None
    state: str = "reviewed"  # state of imported target translations


def import_doc(
    db: Session, proj: StringProject, branch: StringBranch, doc: Doc, opts: ImportOptions, actor: str
) -> dict[str, Any]:
    """Push (R-STR-06): base values create/update keys; target values set translations."""
    from arbiter.strings.qa import check_value

    writable(branch)
    counts = {"created": 0, "updated": 0, "unchanged": 0, "archived": 0, "skipped": 0, "blocked": 0}
    errors: list[str] = list(doc.warnings)
    style = settings_of(proj)["placeholder_style"]
    rules = settings_of(proj)["plural_rules"]
    is_base = opts.lang == proj.base_lang
    if not is_base and opts.lang not in proj.target_langs:
        raise Invalid(f"{opts.lang} is not a language of this project")
    # A base push of a multilingual file (xcstrings, CSV, XLSX) also brings its translations.
    target_langs = [lg for lg in doc.langs if lg in proj.target_langs] if is_base else [opts.lang]
    seen: set[tuple[str, str]] = set()
    for row in doc.rows:
        ns = row.namespace or opts.namespace
        seen.add((ns, row.key))
        try:
            key = find_key(db, proj, branch, ns, row.key)
        except Conflict as e:
            errors.append(f"{row.key}: {e.message}")
            counts["skipped"] += 1
            continue
        base_val = _norm_value(row, row.values.get(proj.base_lang))
        if key is None:
            # A target file creates a key only when it carries the source text (PO, XLIFF).
            if not opts.create_keys or base_val is None:
                counts["skipped"] += 1
                continue
            key = create_key(
                db,
                proj,
                branch,
                name=row.key,
                namespace=ns,
                kind=row.kind,
                description=row.description,
                max_length=row.max_length,
                tags=[*row.tags, *([opts.tag] if opts.tag else [])],
                translatable=row.translatable,
                meta=row.meta,
                base_value=base_val,
                actor=actor,
                actor_type="human",
            )
            counts["created"] += 1
        else:
            if key.archived_at is not None and is_base:
                key.archived_at = None
                history(db, proj, key, branch, "", "restored", actor_type="human", actor_id=actor, via="push")
            if opts.tag and opts.tag not in (key.tags or []):
                key.tags = sorted({*(key.tags or []), opts.tag})
            if is_base and opts.update_changed:
                if row.description and row.description != key.description:
                    key.description = row.description
                if row.meta and row.meta != key.meta:
                    key.meta = {**(key.meta or {}), **row.meta}
                if row.max_length and row.max_length != key.max_length:
                    key.max_length = row.max_length
                if base_val is not None:
                    if row.kind != key.kind:
                        errors.append(
                            f"{row.key}: kind {row.kind} in the file, {key.kind} in the project; skipped"
                        )
                        counts["skipped"] += 1
                        continue
                    res = write_translation(
                        db,
                        proj,
                        branch,
                        key,
                        proj.base_lang,
                        base_val,
                        state="approved",
                        origin="import",
                        event="imported",
                        actor_type="human",
                        actor_id=actor,
                    )
                    counts["updated" if res.changed else "unchanged"] += 1
            elif is_base:
                counts["unchanged"] += 1
        base_eff = effective(db, branch, [key.id], [proj.base_lang]).get((key.id, proj.base_lang))
        for lang in target_langs:
            val = _norm_value(row, row.values.get(lang))
            if val is None or not key.translatable:
                continue
            if not is_valid_value(key.kind, val):
                errors.append(f"{row.key} [{lang}]: value shape does not match the key kind; skipped")
                counts["skipped"] += 1
                continue
            issues = check_value(key, value_of(base_eff), val, lang, style=style, rules=rules)
            blocked = any(i["blocking"] for i in issues)
            state = row.states.get(lang) or opts.state
            if state not in STATES[1:]:
                state = opts.state
            res = write_translation(
                db,
                proj,
                branch,
                key,
                lang,
                val,
                state=state,
                origin="import",
                event="imported",
                actor_type="human",
                actor_id=actor,
                qa=issues,
                blocked=blocked,
                needs_review=blocked,
            )
            counts["blocked"] += 1 if blocked else 0
            if not is_base:
                counts["updated" if res.changed else "unchanged"] += 1
    if opts.archive_missing and is_base:
        for k in visible_keys(db, proj, branch, include_archived=False):
            if k.namespace == opts.namespace and (k.namespace, k.name) not in seen:
                archive_key(db, proj, branch, k, actor, on=True)
                counts["archived"] += 1
    db.flush()
    return {**counts, "warnings": errors[:200]}


def _norm_value(row: KeyRow, v: Value | None) -> Value | None:
    if v is None:
        return None
    if row.kind == "string":
        return v if isinstance(v, str) else v.get("other")
    if isinstance(v, str):
        return {"other": v} if row.kind == "plural" else {"0": v}
    forms = {k: t for k, t in v.items() if t != ""}
    return plurals.sort_forms(forms) if row.kind == "plural" else forms or None


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None
