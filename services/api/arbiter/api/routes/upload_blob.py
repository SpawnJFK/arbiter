"""PUT /v1/uploads/{id}/blob: target of the signed upload URL when the storage backend is local.

No bearer token: the HMAC in the query (upload id + expiry, keyed with the JWT secret)
is the authorization, exactly like a presigned S3 URL. The body is streamed to disk and
refused past the size declared when the upload was created. With the s3 backend this
endpoint does not exist (404); browsers PUT to the bucket instead.
"""

from __future__ import annotations

import contextlib
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from arbiter import storage
from arbiter.api.deps import DB
from arbiter.config import get_settings
from arbiter.errors import NotFound, ServiceError
from arbiter.models import UploadSession

router = APIRouter(tags=["files"])


class TooLarge(ServiceError):
    code = "too_large"
    status = 413


class BadSignature(ServiceError):
    code = "invalid_signature"
    status = 403


@router.put("/uploads/{upload_id}/blob", status_code=204)
async def put_blob(
    upload_id: str,
    request: Request,
    db: DB,
    expires: Annotated[int, Query()],
    token: Annotated[str, Query(min_length=16, max_length=128)],
) -> Response:
    backend = storage.backend()
    if not isinstance(backend, storage.LocalStorage):
        raise NotFound("not found")
    if not storage.check_blob_token(upload_id, expires, token, get_settings().jwt_secret):
        raise BadSignature("the upload URL is invalid or expired")
    u = db.get(UploadSession, upload_id)
    if u is None or u.status != "pending":
        raise NotFound("upload not found")
    final = backend.path(u.storage_key)
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.with_suffix(final.suffix + ".part")
    received = 0
    try:
        with tmp.open("wb") as fh:
            async for chunk in request.stream():
                received += len(chunk)
                if received > u.size:
                    raise TooLarge("the body is larger than the declared size")
                fh.write(chunk)
        tmp.replace(final)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
    return Response(status_code=204)
