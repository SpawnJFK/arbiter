"""All routers. Each module exposes `router` (mounted under /v1) and optionally
`public_router` (mounted at the root, e.g. the strings OTA endpoints under /ota)."""

from __future__ import annotations

import importlib
import pkgutil

from fastapi import APIRouter

ROUTERS: list[APIRouter] = []
PUBLIC_ROUTERS: list[APIRouter] = []
for _m in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
    _mod = importlib.import_module(f"{__name__}.{_m.name}")
    if hasattr(_mod, "router"):
        ROUTERS.append(_mod.router)
    if hasattr(_mod, "public_router"):
        PUBLIC_ROUTERS.append(_mod.public_router)
