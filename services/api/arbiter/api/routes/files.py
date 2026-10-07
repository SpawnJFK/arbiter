"""File upload: POST /files (multipart `file` + `source_lang`).

The upload is validated by extracting it once (R-IN-*): unsupported or damaged files are
refused here with 422 `unsupported_file`, so a quote is never built on a file the pipeline
cannot read back. Counts use the same word rule as quotes (billing.quotes.count_words).
"""

from __future__ import annotations

import hashlib
import posixpath
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Header, UploadFile
from fastapi.responses import JSONResponse

from arbiter import storage
from arbiter.api.deps import DB, Customer
from arbiter.api.routes.projects import idempotent_replay, idempotent_store
from arbiter.billing.quotes import count_words
from arbiter.errors import Invalid
from arbiter.fileproc.base import FormatError, plain_text
from arbiter.fileproc.registry import MAX_FILE_BYTES, detect_and_extract
from arbiter.models import FileAsset, new_id

router = APIRouter(tags=["files"])

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
        "created_at": fa.created_at.isoformat() if fa.created_at else None,
    }


def _read_limited(upload: UploadFile) -> bytes:
    """Read the upload but never more than the limit (+1 byte to detect overflow), R-IN-03."""
    buf = bytearray()
    while chunk := upload.file.read(_CHUNK):
        buf.extend(chunk)
        if len(buf) > MAX_FILE_BYTES:
            raise FormatError("The file is larger than the 1 GB limit.")
    return bytes(buf)


@router.post("/files", status_code=201)
def upload_file(
    p: Customer,
    db: DB,
    file: Annotated[UploadFile, File()],
    source_lang: Annotated[str, Form(min_length=2, max_length=16)],
    idempotency_key: Annotated[str | None, Header()] = None,
) -> Any:
    filename = posixpath.basename((file.filename or "").replace("\\", "/")).strip()
    if not filename:
        raise Invalid("the upload has no file name")
    source_lang = source_lang.strip()
    data = _read_limited(file)
    sha = hashlib.sha256(data).hexdigest()
    payload = {"filename": filename, "source_lang": source_lang, "sha256": sha}
    replay = idempotent_replay(db, p, "files", idempotency_key, payload)
    if replay is not None:
        return replay

    result = detect_and_extract(filename, data, source_lang)  # FormatError -> 422 unsupported_file
    segments = 0
    words = 0
    for unit in result.units:
        for seg in unit.segments:
            text = plain_text(seg.content)
            if text.strip():
                segments += 1
                words += count_words(text)

    file_id = new_id("fil")
    key = storage.make_key(p.org_id, "source", file_id, filename)
    storage.put(key, data)
    fa = FileAsset(
        id=file_id,
        org_id=p.org_id,
        filename=filename,
        format=result.format,
        sha256=sha,
        size=len(data),
        storage_key=key,
        source_lang=source_lang,
        segment_count=segments,
        word_count=words,
    )
    db.add(fa)
    db.flush()
    body = file_view(fa, result.warnings)
    idempotent_store(db, p, "files", idempotency_key, payload, 201, body)
    return JSONResponse(body, status_code=201)
