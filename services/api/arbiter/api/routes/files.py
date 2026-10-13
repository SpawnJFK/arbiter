"""File upload: POST /files (multipart `file` + `source_lang`).

The upload is validated by extracting it once (R-IN-*): unsupported or damaged files are
refused here with 422 `unsupported_file`, so a quote is never built on a file the pipeline
cannot read back. Counts use the same word rule as quotes (billing.quotes.count_words).
"""

from __future__ import annotations

import hashlib
import json
import posixpath
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Header, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from arbiter import storage
from arbiter.api.deps import DB, Customer, require_module
from arbiter.api.routes.projects import idempotent_replay, idempotent_store
from arbiter.billing.quotes import count_words
from arbiter.errors import Invalid
from arbiter.fileproc.base import FormatError, plain_text
from arbiter.fileproc.registry import MAX_FILE_BYTES, detect_and_extract
from arbiter.models import FileAsset, new_id

router = APIRouter(tags=["files"], dependencies=[require_module("tms")])

_CHUNK = 1024 * 1024


def file_view(fa: FileAsset, warnings: list[str] | None = None) -> dict[str, Any]:
    return {
        "id": fa.id,
        "filename": fa.filename,
        "format": fa.format,
        "source_lang": fa.source_lang,
        "size": fa.size,
        "segment_count": fa.segment_count,
        "word_count": fa.word_count,
        "warnings": list(warnings or []),
        "options": fa.options or None,
        "created_at": fa.created_at.isoformat() if fa.created_at else None,
    }


def parse_options(raw: Any) -> dict[str, Any] | None:
    """Format handler options (D-076): a JSON object, given as an object or a JSON string
    (multipart form field). Empty means none. The handler validates the content itself."""
    if raw is None or raw == "" or raw == {}:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raise Invalid("options must be a JSON object") from None
    if not isinstance(raw, dict):
        raise Invalid("options must be a JSON object")
    if len(json.dumps(raw)) > 20_000:
        raise Invalid("options are too large (20 kB at most)")
    return raw or None


def _read_limited(upload: UploadFile) -> bytes:
    """Read the upload but never more than the limit (+1 byte to detect overflow), R-IN-03."""
    buf = bytearray()
    while chunk := upload.file.read(_CHUNK):
        buf.extend(chunk)
        if len(buf) > MAX_FILE_BYTES:
            raise FormatError("The file is larger than the 1 GB limit.")
    return bytes(buf)


def register_file(
    db: Session,
    org_id: str,
    filename: str,
    data: bytes,
    source_lang: str,
    *,
    sha256: str | None = None,
    stored_key: str | None = None,
    options: dict[str, Any] | None = None,
) -> tuple[FileAsset, list[str]]:
    """Validate by extracting once (R-IN-*), count, store and register a source file.

    Shared by POST /files (bytes in the request) and POST /uploads/{id}/complete (bytes
    already in storage at `stored_key`, which is then kept instead of copying the object).
    `options` are the format handler options; they are stored with the file so quote,
    extract and merge read the file the same way.
    """
    # FormatError -> 422 unsupported_file (also for options the handler does not accept)
    result = detect_and_extract(filename, data, source_lang, options)
    segments = 0
    words = 0
    for unit in result.units:
        for seg in unit.segments:
            text = plain_text(seg.content)
            if text.strip():
                segments += 1
                words += count_words(text)

    file_id = new_id("fil")
    if stored_key is None:
        key = storage.make_key(org_id, "source", file_id, filename)
        storage.put(key, data)
    else:
        key = stored_key
    fa = FileAsset(
        id=file_id,
        org_id=org_id,
        filename=filename,
        format=result.format,
        sha256=sha256 or hashlib.sha256(data).hexdigest(),
        size=len(data),
        storage_key=key,
        source_lang=source_lang,
        segment_count=segments,
        word_count=words,
        options=options,
    )
    db.add(fa)
    db.flush()
    return fa, list(result.warnings)


def clean_filename(raw: str | None) -> str:
    filename = posixpath.basename((raw or "").replace("\\", "/")).strip()
    if not filename:
        raise Invalid("the upload has no file name")
    return filename


@router.post("/files", status_code=201)
def upload_file(
    p: Customer,
    db: DB,
    file: Annotated[UploadFile, File()],
    source_lang: Annotated[str, Form(min_length=2, max_length=16)],
    options: Annotated[str | None, Form(max_length=20_000)] = None,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> Any:
    filename = clean_filename(file.filename)
    source_lang = source_lang.strip()
    opts = parse_options(options)
    data = _read_limited(file)
    sha = hashlib.sha256(data).hexdigest()
    payload = {"filename": filename, "source_lang": source_lang, "sha256": sha, "options": opts}
    replay = idempotent_replay(db, p, "files", idempotency_key, payload)
    if replay is not None:
        return replay

    fa, warnings = register_file(db, p.org_id, filename, data, source_lang, sha256=sha, options=opts)
    body = file_view(fa, warnings)
    idempotent_store(db, p, "files", idempotency_key, payload, 201, body)
    return JSONResponse(body, status_code=201)
