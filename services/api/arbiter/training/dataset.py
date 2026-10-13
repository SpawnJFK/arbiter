"""Training data for an org's own model (D-054).

Only segments a human approved (decision "reviewed", state reviewed or delivered) of one
org, one language pair and one domain, and only while org.settings["training_consent"] is
true. Consent is checked on every export, not once: switching it off stops the next job.

Steps: collect -> drop empty or broken targets -> dedupe (one example per source, the most
recent human version wins) -> convert the tagged text to the tag-preserving training form
(<g1>..</g1>, <x2/>, see engines.openai_compatible) -> deterministic train/validation split
by a hash of the source (the same segment always lands on the same side, so a later
re-train never leaks validation data into training) -> JSONL in chat format:

    {"messages": [{"role": "system", ...}, {"role": "user", ...}, {"role": "assistant", ...}]}
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from arbiter.config import Settings, get_settings
from arbiter.engines.openai_compatible import TRAINING_SYSTEM, to_training_text
from arbiter.errors import Invalid
from arbiter.fileproc.base import TaggedParseError
from arbiter.models import Job, Organization, Segment


class ConsentRequired(Invalid):
    code = "training_consent_required"


@dataclass
class Example:
    source: str  # training form
    target: str
    source_tagged: str
    target_tagged: str


@dataclass
class Dataset:
    train: list[Example] = field(default_factory=list)
    validation: list[Example] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


def has_consent(org: Organization) -> bool:
    return bool((org.settings or {}).get("training_consent"))


def _approved(
    session: Session, org_id: str, source_lang: str, target_lang: str, domain: str
) -> list[Segment]:
    q = (
        select(Segment)
        .join(Job, Job.id == Segment.job_id)
        .where(
            Job.org_id == org_id,
            Job.source_lang == source_lang,
            Job.target_lang == target_lang,
            Segment.decision == "reviewed",
            Segment.state.in_(("reviewed", "delivered")),
        )
        .order_by(Segment.updated_at.desc())
    )
    if domain and domain != "any":
        q = q.where(Job.content_type == domain)
    return list(session.execute(q).scalars())


def _is_validation(source_tagged: str, ratio: float) -> bool:
    h = int.from_bytes(hashlib.sha256(source_tagged.encode()).digest()[:4], "big")
    return (h % 10_000) < int(ratio * 10_000)


def build(
    session: Session,
    org: Organization,
    source_lang: str,
    target_lang: str,
    domain: str = "general",
    settings: Settings | None = None,
    *,
    require_consent: bool = True,
) -> Dataset:
    s = settings or get_settings()
    if require_consent and not has_consent(org):
        raise ConsentRequired("training needs the organization's consent (training_consent)")
    segs = _approved(session, org.id, source_lang, target_lang, domain)
    seen: set[str] = set()
    ds = Dataset()
    dropped = {"empty": 0, "duplicate": 0, "unparseable": 0}
    for seg in segs:
        target = (seg.target_tagged or "").strip()
        if not target or not seg.source_plain.strip():
            dropped["empty"] += 1
            continue
        key = seg.source_tagged.strip()
        if key in seen:
            dropped["duplicate"] += 1
            continue
        try:
            ex = Example(
                to_training_text(seg.source_tagged), to_training_text(target), seg.source_tagged, target
            )
        except TaggedParseError:
            dropped["unparseable"] += 1
            continue
        seen.add(key)
        (ds.validation if _is_validation(key, s.training_validation_ratio) else ds.train).append(ex)
    if not ds.validation and len(ds.train) >= 10:
        ds.validation.append(ds.train.pop())  # always keep a held-out set to evaluate on
    words = sum(len(e.source.split()) for e in ds.train)
    ds.stats = {
        "candidates": len(segs),
        "examples": len(ds.train) + len(ds.validation),
        "train": len(ds.train),
        "validation": len(ds.validation),
        "dropped": dropped,
        "train_words": words,
        # rough token estimate (system + user + assistant), used for the cost estimate
        "train_tokens_estimate": int(sum(len(e.source) + len(e.target) + 120 for e in ds.train) / 4),
        "min_examples": s.training_min_examples,
        "enough": len(ds.train) >= s.training_min_examples,
        "consent": has_consent(org),
    }
    return ds


def to_jsonl(examples: list[Example], source_lang: str, target_lang: str) -> bytes:
    system = TRAINING_SYSTEM.format(source_lang=source_lang, target_lang=target_lang)
    lines = [
        json.dumps(
            {
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": e.source},
                    {"role": "assistant", "content": e.target},
                ]
            },
            ensure_ascii=False,
        )
        for e in examples
    ]
    return ("\n".join(lines) + "\n").encode() if lines else b""


def heldout_from_jsonl(data: bytes) -> list[tuple[str, str]]:
    """(source training text, reference training text) pairs of a stored validation file."""
    out = []
    for line in data.decode().splitlines():
        if not line.strip():
            continue
        msgs = json.loads(line)["messages"]
        user = next(m["content"] for m in msgs if m["role"] == "user")
        ref = next(m["content"] for m in msgs if m["role"] == "assistant")
        out.append((user, ref))
    return out
