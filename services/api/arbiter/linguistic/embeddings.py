"""Sentence embeddings for semantic TM lookup (dim 256, matches TmEntry.embedding).

Semantic matches are a fallback for when no fuzzy match is good enough (R-TM-04):
they surface a reformulated sentence with the same meaning as an example for the
engine, never as a leverage match that is billed or auto-inserted.

Providers (settings.embedding_provider):
- "mock": deterministic hashed character-trigram vector, L2 normalised. No network,
  stable across runs, and near-duplicate or reordered sentences land close together.
  Default in dev and test.
- "openai": text-embedding-3-small with dimensions=256, only when a key is configured.
  Vectors from different providers are not comparable: switching provider means
  re-embedding the TM, so a missing key is an error rather than a silent mock fallback.
"""

from __future__ import annotations

import hashlib
import math
import re

import httpx

from arbiter.config import get_settings
from arbiter.models.assets import EMBED_DIM

OPENAI_EMBED_MODEL = "text-embedding-3-small"
_WS = re.compile(r"\s+")


def _mock_one(text: str) -> list[float]:
    vec = [0.0] * EMBED_DIM
    norm = " " + _WS.sub(" ", text.lower()).strip() + " "
    for i in range(len(norm) - 2):
        h = hashlib.blake2b(norm[i : i + 3].encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(h[:4], "big") % EMBED_DIM
        vec[idx] += 1.0 if h[4] & 1 else -1.0
    length = math.sqrt(sum(v * v for v in vec))
    if length == 0.0:
        # Empty text: a fixed unit vector keeps cosine distance defined (no NaN in pgvector).
        vec[0] = 1.0
        return vec
    return [v / length for v in vec]


def _openai(texts: list[str], api_key: str) -> list[list[float]]:
    out: list[list[float]] = []
    with httpx.Client(timeout=30.0) as client:
        for i in range(0, len(texts), 512):
            batch = [t or " " for t in texts[i : i + 512]]
            resp = client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": OPENAI_EMBED_MODEL, "input": batch, "dimensions": EMBED_DIM},
            )
            resp.raise_for_status()
            data = sorted(resp.json()["data"], key=lambda d: d["index"])
            out.extend([list(map(float, d["embedding"])) for d in data])
    return out


def embed(texts: list[str]) -> list[list[float]]:
    """Embed plain texts into unit vectors of EMBED_DIM floats."""
    if not texts:
        return []
    settings = get_settings()
    if settings.embedding_provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("embedding_provider=openai but ARBITER_OPENAI_API_KEY is not set")
        return _openai(texts, settings.openai_api_key)
    return [_mock_one(t) for t in texts]
