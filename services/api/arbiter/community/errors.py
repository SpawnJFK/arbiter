"""Errors raised by community and billing services.

The API layer maps them to HTTP: NotFound 404, Forbidden 403, Conflict 409, Invalid 422.
All subclass ValueError so plain callers can catch one type.
"""

from __future__ import annotations

from typing import Any


class ServiceError(ValueError):
    code = "error"
    status = 400

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFound(ServiceError):
    code = "not_found"
    status = 404


class Forbidden(ServiceError):
    code = "forbidden"
    status = 403


class Conflict(ServiceError):
    code = "conflict"
    status = 409


class Invalid(ServiceError):
    code = "invalid"
    status = 422
