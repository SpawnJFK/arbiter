"""Blob storage for uploaded files, outputs and evidence packs.

Two backends behind one interface (`Storage`), picked by ARBITER_STORAGE_BACKEND:

* LocalStorage (default for dev and test): files under settings.storage_dir. Direct
  uploads go to the API's own signed endpoint PUT /v1/uploads/{id}/blob, so the browser
  flow is the same as in production. Downloads are streamed by the API.
* S3Storage: any S3-compatible object store (Hetzner Object Storage in production).
  Browsers upload straight to the bucket with a presigned PUT and download through a
  presigned GET, so large files never pass through Cloudflare or the API.

Callers keep using the module functions (make_key, put, get, delete, exists, size,
presign_put, presign_get); they delegate to the configured backend.
Keys are '<org_id>/<kind>/<id>/<filename>'; never user-controlled paths.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, urlencode

from arbiter.config import Settings, get_settings

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def make_key(org_id: str, kind: str, obj_id: str, filename: str) -> str:
    name = _SAFE.sub("_", filename).strip("._") or "file"
    return f"{_SAFE.sub('_', org_id)}/{kind}/{_SAFE.sub('_', obj_id)}/{name[:180]}"


@dataclass(frozen=True)
class PresignedRequest:
    """What a client needs to send the bytes itself."""

    url: str
    method: str
    headers: dict[str, str] = field(default_factory=dict)
    expires_at: int = 0  # unix seconds


class Storage(Protocol):
    name: str

    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...  # FileNotFoundError when missing
    def delete(self, key: str) -> None: ...
    def size(self, key: str) -> int | None: ...  # None when missing
    def presign_put(self, key: str, *, upload_id: str, content_type: str, ttl: int) -> PresignedRequest: ...
    def presign_get(self, key: str, *, filename: str, content_type: str, ttl: int) -> str | None: ...


# --------------------------------------------------------------------------- local


def blob_token(upload_id: str, expires: int, secret: str) -> str:
    """HMAC for the local direct-upload endpoint: binds the upload id to an expiry."""
    msg = f"upload:{upload_id}:{expires}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def check_blob_token(upload_id: str, expires: int, token: str, secret: str, now: float | None = None) -> bool:
    if expires < int(now if now is not None else time.time()):
        return False
    return hmac.compare_digest(blob_token(upload_id, expires, secret), token or "")


class LocalStorage:
    name = "local"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _root(self) -> Path:
        root = Path(self._settings.storage_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    def path(self, key: str) -> Path:
        root = self._root()
        p = (root / key).resolve()
        if root not in p.parents:
            raise ValueError("invalid storage key")
        return p

    def put(self, key: str, data: bytes) -> None:
        self.put_chunks(key, [data])

    def put_chunks(self, key: str, chunks: Iterable[bytes]) -> int:
        """Atomic write from an iterable of chunks; returns the byte count."""
        p = self.path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        n = 0
        with tmp.open("wb") as fh:
            for chunk in chunks:
                fh.write(chunk)
                n += len(chunk)
        tmp.replace(p)
        return n

    def get(self, key: str) -> bytes:
        return self.path(key).read_bytes()

    def delete(self, key: str) -> None:
        p = self.path(key)
        if p.exists():
            p.unlink()

    def size(self, key: str) -> int | None:
        p = self.path(key)
        return p.stat().st_size if p.is_file() else None

    def presign_put(self, key: str, *, upload_id: str, content_type: str, ttl: int) -> PresignedRequest:
        expires = int(time.time()) + ttl
        token = blob_token(upload_id, expires, self._settings.jwt_secret)
        base = self._settings.public_base_url.rstrip("/")
        query = urlencode({"expires": expires, "token": token})
        url = f"{base}/v1/uploads/{quote(upload_id)}/blob?{query}"
        return PresignedRequest(
            url=url, method="PUT", headers={"Content-Type": content_type}, expires_at=expires
        )

    def presign_get(self, key: str, *, filename: str, content_type: str, ttl: int) -> str | None:
        return None  # the API streams local files itself


# --------------------------------------------------------------------------- s3


class S3Storage:
    name = "s3"

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        if not settings.s3_bucket:
            raise RuntimeError("ARBITER_S3_BUCKET must be set when ARBITER_STORAGE_BACKEND=s3")
        self._settings = settings
        self.bucket = settings.s3_bucket
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            import boto3
            from botocore.config import Config

            s = self._settings
            self._client = boto3.client(
                "s3",
                endpoint_url=s.s3_endpoint_url or None,
                region_name=s.s3_region or None,
                aws_access_key_id=s.s3_access_key_id or None,
                aws_secret_access_key=s.s3_secret_access_key or None,
                config=Config(
                    signature_version="s3v4",
                    s3={"addressing_style": "path" if s.s3_path_style else "virtual"},
                    retries={"max_attempts": 5, "mode": "standard"},
                ),
            )
        return self._client

    @staticmethod
    def _missing(exc: Exception) -> bool:
        code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
        return code in ("404", "NoSuchKey", "NotFound")

    def put(self, key: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)

    def get(self, key: str) -> bytes:
        from botocore.exceptions import ClientError

        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as e:
            if self._missing(e):
                raise FileNotFoundError(key) from None
            raise
        return obj["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def size(self, key: str) -> int | None:
        from botocore.exceptions import ClientError

        try:
            head = self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as e:
            if self._missing(e):
                return None
            raise
        return int(head["ContentLength"])

    def presign_put(self, key: str, *, upload_id: str, content_type: str, ttl: int) -> PresignedRequest:
        url = self.client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=ttl,
            HttpMethod="PUT",
        )
        return PresignedRequest(
            url=url, method="PUT", headers={"Content-Type": content_type}, expires_at=int(time.time()) + ttl
        )

    def presign_get(self, key: str, *, filename: str, content_type: str, ttl: int) -> str | None:
        disposition = f"attachment; filename*=UTF-8''{quote(filename)}"
        return self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ResponseContentDisposition": disposition,
                "ResponseContentType": content_type,
            },
            ExpiresIn=ttl,
            HttpMethod="GET",
        )


# --------------------------------------------------------------------------- selection


def build(settings: Settings) -> Storage:
    if settings.storage_backend == "s3":
        return S3Storage(settings)
    return LocalStorage(settings)


@lru_cache
def _cached(settings_id: int) -> Storage:
    return build(get_settings())


_override: Storage | None = None


def backend() -> Storage:
    """The configured backend. Tests swap it with `use()`."""
    if _override is not None:
        return _override
    return _cached(id(get_settings()))


def use(storage: Storage | None) -> None:
    """Replace the backend (tests). `use(None)` restores the configured one."""
    global _override
    _override = storage


def put(key: str, data: bytes) -> None:
    backend().put(key, data)


def get(key: str) -> bytes:
    return backend().get(key)


def delete(key: str) -> None:
    backend().delete(key)


def size(key: str) -> int | None:
    return backend().size(key)


def exists(key: str) -> bool:
    return backend().size(key) is not None


def presign_put(key: str, *, upload_id: str, content_type: str, ttl: int | None = None) -> PresignedRequest:
    ttl = ttl or get_settings().upload_url_ttl_seconds
    return backend().presign_put(key, upload_id=upload_id, content_type=content_type, ttl=ttl)


def presign_get(key: str, *, filename: str, content_type: str, ttl: int | None = None) -> str | None:
    """A short-lived download URL, or None when the backend streams through the API."""
    ttl = ttl or get_settings().download_url_ttl_seconds
    return backend().presign_get(key, filename=filename, content_type=content_type, ttl=ttl)
