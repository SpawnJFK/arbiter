"""Direct uploads (R-IN-03): the client sends the bytes straight to storage, then completes.

    POST /v1/uploads                  {filename, size, content_type, source_lang}
        -> 201 {upload_id, url, method, headers, expires_at, max_bytes, backend}
    PUT  <url>                        the raw bytes, with the returned headers
    POST /v1/uploads/{id}/complete    -> 201 the File view (same as POST /files)

With the s3 backend `url` is a presigned PUT to the bucket, so a 1 GB file never passes
through Cloudflare (whose proxied request bodies are capped) or the API. With the local
backend `url` is PUT /v1/uploads/{id}/blob?expires=..&token=.. on this API, an HMAC-signed
URL that needs no bearer token, so dev, e2e and the production flow are the same.

`complete` checks the stored object's size against the declared size, then runs the same
extraction and registration as POST /files. Unsupported or damaged files are refused
there with 422 `unsupported_file` and the object is deleted.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from arbiter import storage
from arbiter.api.deps import DB, Customer, require_module
from arbiter.api.routes.files import clean_filename, file_view, parse_options, register_file
from arbiter.api.routes.projects import idempotent_replay, idempotent_store
from arbiter.config import get_settings
from arbiter.errors import Conflict, Invalid, NotFound
from arbiter.fileproc.base import FormatError
from arbiter.fileproc.registry import MAX_FILE_BYTES, get_handler
from arbiter.models import FileAsset, UploadSession, new_id, utcnow

router = APIRouter(tags=["files"], dependencies=[require_module("tms")])


class UploadExpired(Conflict):
    code = "upload_expired"


class UploadMissing(Conflict):
    code = "upload_missing"


class SizeMismatch(Invalid):
    code = "size_mismatch"


class UploadIn(BaseModel):
    filename: str = Field(min_length=1, max_length=400)
    size: int = Field(ge=1, le=MAX_FILE_BYTES)
    content_type: str = Field(default="application/octet-stream", min_length=1, max_length=200)
    source_lang: str = Field(min_length=2, max_length=16)
    # Format handler options (D-076), e.g. {"max_line_length": 42} for subtitles or XML rules.
    options: dict[str, Any] | None = None


def upload_view(u: UploadSession, req: storage.PresignedRequest, backend: str) -> dict[str, Any]:
    return {
        "upload_id": u.id,
        "url": req.url,
        "method": req.method,
        "headers": dict(req.headers),
        "expires_at": u.expires_at.isoformat(),
        "max_bytes": MAX_FILE_BYTES,
        "size": u.size,
        "backend": backend,
    }


def _content_type(raw: str) -> str:
    ct = raw.strip().split(";", 1)[0].strip().lower()
    if not ct or "/" not in ct or any(c in ct for c in "\r\n "):
        return "application/octet-stream"
    return ct


@router.post("/uploads", status_code=201)
def create_upload(
    body: UploadIn, p: Customer, db: DB, idempotency_key: Annotated[str | None, Header()] = None
) -> Any:
    filename = clean_filename(body.filename)
    opts = parse_options(body.options)
    # unsupported extension or options the handler refuses -> 422 before any bytes move
    get_handler(filename, opts)
    source_lang = body.source_lang.strip()
    content_type = _content_type(body.content_type)
    payload = {
        "filename": filename,
        "size": body.size,
        "ct": content_type,
        "source_lang": source_lang,
        "options": opts,
    }
    replay = idempotent_replay(db, p, "uploads", idempotency_key, payload)
    if replay is not None:
        return replay

    settings = get_settings()
    upload_id = new_id("upl")
    key = storage.make_key(p.org_id, "source", upload_id, filename)
    presigned = storage.presign_put(key, upload_id=upload_id, content_type=content_type)
    u = UploadSession(
        id=upload_id,
        org_id=p.org_id,
        created_by=(p.user.id if p.user else (p.api_key.id if p.api_key else "")),
        filename=filename,
        size=body.size,
        content_type=content_type,
        source_lang=source_lang,
        options=opts,
        storage_key=key,
        status="pending",
        expires_at=utcnow() + timedelta(seconds=settings.upload_url_ttl_seconds),
    )
    db.add(u)
    db.flush()
    out = upload_view(u, presigned, storage.backend().name)
    idempotent_store(db, p, "uploads", idempotency_key, payload, 201, out)
    return JSONResponse(out, status_code=201)


def _session(db: DB, org_id: str, upload_id: str, lock: bool = False) -> UploadSession:
    q = select(UploadSession).where(UploadSession.id == upload_id, UploadSession.org_id == org_id)
    if lock:
        q = q.with_for_update()
    u = db.execute(q).scalar_one_or_none()
    if u is None:
        raise NotFound("upload not found")  # another org's upload is a 404, never a 403
    return u


@router.get("/uploads/{upload_id}")
def get_upload(upload_id: str, p: Customer, db: DB) -> dict[str, Any]:
    u = _session(db, p.org_id, upload_id)
    return {
        "upload_id": u.id,
        "filename": u.filename,
        "size": u.size,
        "status": u.status,
        "file_id": u.file_id,
        "expires_at": u.expires_at.isoformat(),
    }


@router.post("/uploads/{upload_id}/complete", status_code=201)
def complete_upload(
    upload_id: str, p: Customer, db: DB, idempotency_key: Annotated[str | None, Header()] = None
) -> Any:
    payload = {"upload_id": upload_id}
    replay = idempotent_replay(db, p, "uploads.complete", idempotency_key, payload)
    if replay is not None:
        return replay
    u = _session(db, p.org_id, upload_id, lock=True)
    if u.status == "completed" and u.file_id:
        fa = db.get(FileAsset, u.file_id)
        if fa is not None:  # completing twice returns the same file
            return JSONResponse(file_view(fa), status_code=201)
    if u.status == "rejected":
        raise UploadExpired("this upload was rejected; start a new upload")

    stored = storage.size(u.storage_key)
    if stored is None:
        if u.expires_at <= utcnow():
            raise UploadExpired("the upload URL expired before the file arrived; start a new upload")
        raise UploadMissing("the file has not arrived in storage yet")
    if stored != u.size or stored > MAX_FILE_BYTES:
        storage.delete(u.storage_key)
        u.status = "rejected"
        db.flush()
        db.commit()  # keep the rejection even though the request fails
        raise SizeMismatch(
            "the stored file size does not match the declared size",
            {"declared": u.size, "stored": stored},
        )
    data = storage.get(u.storage_key)
    sha = hashlib.sha256(data).hexdigest()
    try:
        fa, warnings = register_file(
            db,
            p.org_id,
            u.filename,
            data,
            u.source_lang,
            sha256=sha,
            stored_key=u.storage_key,
            options=u.options,
        )
    except FormatError:
        storage.delete(u.storage_key)
        u.status = "rejected"
        db.flush()
        db.commit()
        raise
    u.status = "completed"
    u.file_id = fa.id
    u.completed_at = utcnow()
    db.flush()
    body = file_view(fa, warnings)
    idempotent_store(db, p, "uploads.complete", idempotency_key, payload, 201, body)
    return JSONResponse(body, status_code=201)
