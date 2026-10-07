"""All routers. Each module exposes `router`; add new modules to ROUTERS."""

from __future__ import annotations

import importlib
import pkgutil

from fastapi import APIRouter

ROUTERS: list[APIRouter] = []
for _m in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
    _mod = importlib.import_module(f"{__name__}.{_m.name}")
    if hasattr(_mod, "router"):
        ROUTERS.append(_mod.router)
