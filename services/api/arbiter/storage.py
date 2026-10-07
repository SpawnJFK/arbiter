"""Blob storage for uploaded files, outputs and evidence packs.

Local disk under settings.storage_dir (a Docker volume in production). The interface is
three functions so an S3-compatible backend can replace it without touching callers.
Keys are '<org_id>/<kind>/<id>/<filename>'; never user-controlled paths.
"""

from __future__ import annotations

import re
from pathlib import Path

from arbiter.config import get_settings

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _root() -> Path:
    root = Path(get_settings().storage_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def make_key(org_id: str, kind: str, obj_id: str, filename: str) -> str:
    name = _SAFE.sub("_", filename).strip("._") or "file"
    return f"{_SAFE.sub('_', org_id)}/{kind}/{_SAFE.sub('_', obj_id)}/{name[:180]}"


def _path(key: str) -> Path:
    root = _root()
    p = (root / key).resolve()
    if root not in p.parents:
        raise ValueError("invalid storage key")
    return p


def put(key: str, data: bytes) -> None:
    p = _path(key)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(p)


def get(key: str) -> bytes:
    return _path(key).read_bytes()


def delete(key: str) -> None:
    p = _path(key)
    if p.exists():
        p.unlink()
