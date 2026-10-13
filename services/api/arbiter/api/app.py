"""FastAPI application: `uvicorn arbiter.api.app:app`. Routes follow docs/api-contract.md."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from arbiter import observability
from arbiter.config import get_settings
from arbiter.domain.states import IllegalTransition
from arbiter.errors import ServiceError
from arbiter.fileproc.base import FormatError
from arbiter.platform.audit import AuditContextMiddleware

log = logging.getLogger("arbiter.api")


def _err(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message, "details": details or {}}}, status_code=status
    )


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.env == "prod" and settings.jwt_secret.startswith("dev-only"):
        raise RuntimeError("ARBITER_JWT_SECRET must be set in production")
    if settings.env == "prod" and settings.secrets_key.startswith("dev-only"):
        raise RuntimeError("ARBITER_SECRETS_KEY must be set in production")
    app = FastAPI(title="Arbiter API", version="1.0.0", docs_url="/docs", openapi_url="/openapi.json")
    if settings.env in ("staging", "prod") and settings.storage_backend == "local":
        log.warning("ARBITER_STORAGE_BACKEND=local outside dev: files live on this host only")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(AuditContextMiddleware)  # client IP and user agent for audit rows

    @app.exception_handler(ServiceError)
    async def _service(_: Request, e: ServiceError) -> JSONResponse:
        return _err(e.status, e.code, e.message, e.details)

    @app.exception_handler(FormatError)
    async def _format(_: Request, e: FormatError) -> JSONResponse:
        return _err(422, "unsupported_file", str(e))

    @app.exception_handler(IllegalTransition)
    async def _illegal(_: Request, e: IllegalTransition) -> JSONResponse:
        return _err(409, "illegal_state", f"cannot go from {e.src} to {e.dst}")

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError) -> JSONResponse:
        # jsonable_encoder: error contexts may hold Decimal limits (money fields) or exceptions
        return _err(422, "validation_error", "request is invalid", {"errors": jsonable_encoder(e.errors())})

    @app.exception_handler(LookupError)
    async def _lookup(_: Request, e: LookupError) -> JSONResponse:
        return _err(404, "not_found", str(e) or "not found")

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, e: Exception) -> JSONResponse:
        # Reported without the request body; the client gets a generic message.
        log.exception("unhandled error")
        observability.capture_exception(e, "api")
        return _err(500, "internal_error", "Something went wrong on our side. Please try again.")

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict:
        # `commit` lets scripts/verify-deployed-version.mjs prove what is running.
        return {"ok": True, "commit": settings.git_sha, "version": settings.version}

    from arbiter.api.routes import ROUTERS

    for router in ROUTERS:
        app.include_router(router, prefix="/v1")
    if observability.setup_tracing("arbiter-api", app=app):
        from arbiter import db

        observability.setup_tracing("arbiter-api", engine=db.get_engine())
    return app


app = create_app()
