"""Releases and over-the-air (OTA) bundles (R-STR-REL-*).

A release freezes the strings of a branch: one JSON bundle per language (plus platform files
on request) written to storage, a content hash, and a version label. Published releases are
served without auth at

    /ota/{public_id}/{version_label | release id}/{lang}.json   immutable, cache for a year
    /ota/{public_id}/latest/{lang}.json                          short cache + ETag revalidation
    /ota/{public_id}/{ref}/manifest.json                         languages, hashes, URLs

Bundle shape: {"<key>": "text", "<plural key>": {"one": "...", "other": "..."},
"<array key>": ["...", "..."]}; a key in a namespace is "<namespace>:<key>" (i18next style).
What ships (R-STR-REL-01): translations at or above settings.release_min_state that are not
blocked; with settings.fallback_to_base (default) the base text fills the gaps, so an app
never shows a raw key. Private projects need a distribution token (?token= or the
X-Distribution-Token header); only its SHA-256 is stored.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arbiter import storage, webhooks
from arbiter.config import get_settings
from arbiter.errors import Conflict, Invalid, NotFound
from arbiter.models import StringProject, StringRelease, utcnow
from arbiter.strings import formats, service

_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
RELEASE_EVENT = "strings.release.published"


def bundle_messages(doc: Any, lang: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for r in doc.rows:
        if lang not in r.values:
            continue
        name = f"{r.namespace}:{r.key}" if r.namespace else r.key
        v = r.values[lang]
        if r.kind == "array" and isinstance(v, dict):
            out[name] = [v[k] for k in sorted(v, key=lambda x: int(x) if x.isdigit() else 0)]
        else:
            out[name] = v
    return out


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _next_label(db: Session, proj: StringProject) -> str:
    n = db.execute(
        select(func.count()).select_from(StringRelease).where(StringRelease.project_id == proj.id)
    ).scalar_one()
    label = f"v{n + 1}"
    while db.execute(
        select(StringRelease.id).where(
            StringRelease.project_id == proj.id, StringRelease.version_label == label
        )
    ).first():
        n += 1
        label = f"v{n + 1}"
    return label


def create_release(
    db: Session,
    proj: StringProject,
    branch: Any,
    *,
    version_label: str | None,
    langs: list[str] | None,
    extra_formats: list[str] | None,
    publish: bool,
    actor: str | None,
) -> StringRelease:
    label = (version_label or "").strip() or _next_label(db, proj)
    if not _LABEL.match(label) or label in ("latest", "manifest"):
        raise Invalid("version labels use letters, digits, '.', '_', '+', '-' (and are not 'latest')")
    if db.execute(
        select(StringRelease.id).where(
            StringRelease.project_id == proj.id, StringRelease.version_label == label
        )
    ).first():
        raise Conflict(f"release {label!r} already exists")
    all_langs = service.project_langs(proj)
    langs = [service.norm_locale(lg) for lg in (langs or all_langs)]
    bad = [lg for lg in langs if lg not in all_langs]
    if bad:
        raise Invalid(f"not languages of this project: {', '.join(bad)}")
    for f in extra_formats or []:
        formats.get(f)
    s = service.settings_of(proj)
    doc = service.export_doc(
        db,
        proj,
        branch,
        langs,
        min_state=s["release_min_state"],
        include_blocked=False,
        fallback_to_base=bool(s["fallback_to_base"]),
    )
    rel = StringRelease(
        project_id=proj.id,
        branch_id=branch.id,
        version_label=label,
        status="draft",
        langs=langs,
        bundles={},
        content_hash="",
        key_count=sum(1 for r in doc.rows if r.translatable),
        created_by=actor,
    )
    db.add(rel)
    db.flush()
    bundles: dict[str, Any] = {}
    digest = hashlib.sha256()
    for lang in langs:
        data = canonical(bundle_messages(doc, lang))
        sha = hashlib.sha256(data).hexdigest()
        key = storage.make_key(proj.org_id, "strings", rel.id, f"{lang}.json")
        storage.put(key, data)
        entry: dict[str, Any] = {"json": {"key": key, "sha256": sha, "bytes": len(data)}}
        for f in extra_formats or []:
            spec = formats.get(f)
            if spec.multilingual:
                continue  # multilingual formats are built once below
            fdata = spec.render(doc, lang)
            fkey = storage.make_key(proj.org_id, "strings", rel.id, f"{lang}.{f}.{spec.extension}")
            storage.put(fkey, fdata)
            entry[f] = {"key": fkey, "sha256": hashlib.sha256(fdata).hexdigest(), "bytes": len(fdata)}
        bundles[lang] = entry
        digest.update(f"{lang}:{sha}\n".encode())
    for f in extra_formats or []:
        spec = formats.get(f)
        if spec.multilingual:
            fdata = spec.render(doc, proj.base_lang)
            fkey = storage.make_key(proj.org_id, "strings", rel.id, f"all.{f}.{spec.extension}")
            storage.put(fkey, fdata)
            bundles.setdefault("_all", {})[f] = {
                "key": fkey,
                "sha256": hashlib.sha256(fdata).hexdigest(),
                "bytes": len(fdata),
            }
    rel.bundles = bundles
    rel.content_hash = digest.hexdigest()
    db.flush()
    if publish:
        publish_release(db, proj, rel)
    return rel


def publish_release(db: Session, proj: StringProject, rel: StringRelease) -> StringRelease:
    if rel.status == "published":
        return rel
    rel.status = "published"
    rel.published_at = utcnow()
    db.flush()
    webhooks.emit(
        db,
        proj.org_id,
        RELEASE_EVENT,
        {
            "project_id": proj.id,
            "release_id": rel.id,
            "version_label": rel.version_label,
            "content_hash": rel.content_hash,
            "langs": rel.langs,
            "ota": ota_urls(proj, rel),
        },
    )
    return rel


def ota_base() -> str:
    return get_settings().public_base_url.rstrip("/")


def ota_urls(proj: StringProject, rel: StringRelease) -> dict[str, Any]:
    base = f"{ota_base()}/ota/{proj.public_id}"
    return {
        "manifest": f"{base}/{rel.version_label}/manifest.json",
        "latest_manifest": f"{base}/latest/manifest.json",
        "langs": {
            lang: {
                "versioned": f"{base}/{rel.version_label}/{lang}.json",
                "latest": f"{base}/latest/{lang}.json",
            }
            for lang in rel.langs
        },
    }


def release_view(proj: StringProject, rel: StringRelease) -> dict[str, Any]:
    files = {
        lang: {f: {"sha256": e["sha256"], "bytes": e["bytes"]} for f, e in entry.items()}
        for lang, entry in (rel.bundles or {}).items()
    }
    return {
        "id": rel.id,
        "version_label": rel.version_label,
        "status": rel.status,
        "branch_id": rel.branch_id,
        "langs": rel.langs,
        "content_hash": rel.content_hash,
        "key_count": rel.key_count,
        "files": files,
        "ota": ota_urls(proj, rel) if rel.status == "published" else None,
        "created_at": rel.created_at.isoformat() if rel.created_at else None,
        "published_at": rel.published_at.isoformat() if rel.published_at else None,
    }


def list_releases(db: Session, proj: StringProject, offset: int, limit: int) -> list[StringRelease]:
    return list(
        db.execute(
            select(StringRelease)
            .where(StringRelease.project_id == proj.id)
            .order_by(StringRelease.created_at.desc(), StringRelease.id.desc())
            .offset(offset)
            .limit(limit + 1)
        ).scalars()
    )


def get_release(db: Session, proj: StringProject, ref: str) -> StringRelease:
    rel = db.execute(
        select(StringRelease).where(
            StringRelease.project_id == proj.id,
            (StringRelease.id == ref) | (StringRelease.version_label == ref),
        )
    ).scalar_one_or_none()
    if rel is None:
        raise NotFound("release not found")
    return rel


def release_file(rel: StringRelease, lang: str, fmt: str) -> tuple[bytes, str, str]:
    """(data, content type, filename) of one stored bundle file."""
    entry = (rel.bundles or {}).get(lang) or {}
    if fmt not in entry:
        raise NotFound(f"no {fmt} file for {lang} in this release")
    spec_ext = "json" if fmt == "json" else formats.get(fmt).extension
    ctype = "application/json" if fmt == "json" else formats.get(fmt).content_type
    return storage.get(entry[fmt]["key"]), ctype, f"{lang}.{spec_ext}"


# ------------------------------------------------------------------ distribution token


def new_distribution_token(db: Session, proj: StringProject) -> str:
    token = "sdt_" + secrets.token_urlsafe(24)
    proj.settings = {
        **(proj.settings or {}),
        "private": True,
        "distribution_token_hash": hashlib.sha256(token.encode()).hexdigest(),
    }
    db.flush()
    return token


def token_ok(proj: StringProject, token: str | None) -> bool:
    s = proj.settings or {}
    if not s.get("private"):
        return True
    want = s.get("distribution_token_hash")
    if not want or not token:
        return False
    return hmac.compare_digest(want, hashlib.sha256(token.encode()).hexdigest())


# ------------------------------------------------------------------ public OTA lookup


def resolve_public(db: Session, public_id: str, ref: str) -> tuple[StringProject, StringRelease]:
    proj = db.execute(
        select(StringProject).where(StringProject.public_id == public_id, StringProject.archived_at.is_(None))
    ).scalar_one_or_none()
    if proj is None:
        raise NotFound("not found")
    stmt = select(StringRelease).where(
        StringRelease.project_id == proj.id, StringRelease.status == "published"
    )
    if ref == "latest":
        stmt = stmt.order_by(StringRelease.published_at.desc(), StringRelease.id.desc()).limit(1)
    else:
        stmt = stmt.where((StringRelease.version_label == ref) | (StringRelease.id == ref))
    rel = db.execute(stmt).scalars().first()
    if rel is None:
        raise NotFound("not found")
    return proj, rel
