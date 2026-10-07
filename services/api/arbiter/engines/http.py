"""Shared HTTP plumbing for real providers: retry policy and JSON extraction.

Why a shared module: every provider fails the same ways (429 rate limit, 5xx, 529
"overloaded", dropped connections) and every LLM sometimes wraps JSON in prose or code
fences. Handling that once keeps the provider modules small and the behaviour identical.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

import httpx
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential, wait_none

from arbiter.contracts import EngineError

RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}


class RetryableError(EngineError):
    """Transient provider failure (rate limit, overload, 5xx, network)."""


class BadJsonError(EngineError):
    """The model answered, but not with a JSON object. Worth exactly one more try."""


def check_response(resp: httpx.Response, provider: str) -> None:
    if resp.status_code in RETRY_STATUS:
        raise RetryableError(f"{provider}: HTTP {resp.status_code}: {resp.text[:300]}")
    if resp.status_code >= 400:
        # 400/401/403/404 will not get better by retrying. Never echo request headers (keys).
        raise EngineError(f"{provider}: HTTP {resp.status_code}: {resp.text[:300]}")


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, (RetryableError, BadJsonError, httpx.TransportError))


def with_retry[T](fn: Callable[[], T], *, attempts: int = 4, backoff: float = 1.0) -> T:
    """Run fn with exponential backoff on transient errors. backoff=0 disables sleeping
    (tests). The final exception is re-raised as EngineError so callers only catch one type."""
    retrying = Retrying(
        stop=stop_after_attempt(max(1, attempts)),
        wait=wait_exponential(multiplier=backoff, min=0, max=30 * backoff) if backoff else wait_none(),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    try:
        return retrying(fn)
    except EngineError:
        raise
    except httpx.HTTPError as e:
        raise EngineError(f"network error: {e}") from e


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def extract_json(text: str) -> dict[str, Any]:
    """Parse a JSON object from model text: plain JSON, fenced JSON, or JSON embedded in prose."""
    text = text.strip()
    candidates = [text]
    candidates += [m.group(1).strip() for m in _FENCE_RE.finditer(text)]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for c in candidates:
        try:
            value = json.loads(c)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict):
            return value
    raise BadJsonError(f"model did not return a JSON object: {text[:200]!r}")
