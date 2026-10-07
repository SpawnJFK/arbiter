"""Service errors shared by every module (defined in community.errors, re-exported here)."""

from arbiter.community.errors import Conflict, Forbidden, Invalid, NotFound, ServiceError

__all__ = ["Conflict", "Forbidden", "Invalid", "NotFound", "ServiceError"]
