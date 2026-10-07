"""Cross-module contracts.

These dataclasses and protocols are the seams between linguistic assets, engines,
quality (QA, QE, senate) and the pipeline. Each side may change its internals freely;
changing anything here is a decision (record it in docs/decisions.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Protocol

# ---------------------------------------------------------------- linguistic assets

TermKind = Literal["mandatory", "preferred", "forbidden", "do_not_translate"]
MatchKind = Literal["context", "exact", "fuzzy", "semantic"]


@dataclass(frozen=True)
class TermHit:
    """A glossary term found in a source segment (or, for forbidden terms, to watch in the target)."""

    term_id: str
    kind: TermKind
    source_term: str
    target_term: str | None  # DNT: None (target must equal source); forbidden: the forbidden target string
    start: int  # char span in source_plain
    end: int
    case_sensitive: bool = False
    note: str = ""


@dataclass(frozen=True)
class TermViolation:
    term_id: str
    kind: TermKind
    code: str  # term_missing | term_forbidden | dnt_changed | term_preferred_missing
    severity: Literal["error", "warning"]
    message: str


@dataclass(frozen=True)
class TmMatch:
    entry_id: str
    kind: MatchKind
    score: float  # 101 context, 100 exact, 0..99 fuzzy, semantic similarity*100
    source_tagged: str
    target_tagged: str


# ---------------------------------------------------------------- engines


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    characters: int = 0
    cost: Decimal = Decimal("0")


@dataclass
class MtRequest:
    source_tagged: str
    source_lang: str
    target_lang: str
    terms: list[TermHit] = field(default_factory=list)
    context_before: str = ""
    context_after: str = ""
    style_rules: list[str] = field(default_factory=list)
    formality: str | None = None
    max_length: int | None = None
    tm_examples: list[TmMatch] = field(default_factory=list)


@dataclass
class MtResult:
    target_tagged: str
    engine: str
    model_version: str
    usage: Usage = field(default_factory=Usage)
    error: str | None = None


class MtEngine(Protocol):
    name: str
    supports_glossary: bool

    def available(self) -> bool: ...

    def translate(self, requests: list[MtRequest]) -> list[MtResult]: ...


class LlmClient(Protocol):
    """A chat model returning JSON. Every judge, senate role and editor goes through this."""

    name: str

    def available(self) -> bool: ...

    def complete_json(
        self,
        system: str,
        user: str,
        *,
        schema_hint: str = "",
        max_tokens: int = 2000,
        temperature: float = 0.0,
    ) -> tuple[dict[str, Any], Usage, str]:
        """Returns (parsed_json, usage, model_version). Raises EngineError on failure."""
        ...


class EngineError(Exception):
    pass


# ---------------------------------------------------------------- quality

Severity = Literal["neutral", "minor", "major", "critical"]
SEVERITY_WEIGHT: dict[str, int] = {"neutral": 0, "minor": 1, "major": 5, "critical": 25}
MQM_DIMENSIONS = (
    "terminology",
    "accuracy",
    "linguistic_conventions",
    "style",
    "locale_conventions",
    "audience_appropriateness",
    "design_and_markup",
)


@dataclass(frozen=True)
class QaIssue:
    code: str  # e.g. tag_missing, number_mismatch, term_missing, empty_target, length_exceeded
    severity: Literal["error", "warning", "info"]
    message: str
    blocking: bool  # blocking issues zero the QE score and prevent auto-approval


@dataclass(frozen=True)
class MqmError:
    dimension: str  # one of MQM_DIMENSIONS
    severity: Severity
    span: str
    explanation: str
    role: str = ""  # which judge / senate role raised it
    fix: str | None = None


@dataclass
class SegmentContext:
    """Everything a judge needs about one segment."""

    segment_id: str
    source_tagged: str
    target_tagged: str
    source_lang: str
    target_lang: str
    content_type: str = "general"
    terms: list[TermHit] = field(default_factory=list)
    style_rules: list[str] = field(default_factory=list)
    tm_matches: list[TmMatch] = field(default_factory=list)
    context_before: str = ""
    context_after: str = ""
    max_length: int | None = None
    document_targets: list[tuple[str, str]] = field(
        default_factory=list
    )  # (source, target) of other segments


Decision = Literal["auto_approve", "senate", "review", "blocked"]


@dataclass
class QeResult:
    score: float  # 0..100
    errors: list[MqmError]
    hard_issues: list[QaIssue]
    model_version: str
    usage: Usage = field(default_factory=Usage)


@dataclass
class SenateVerdict:
    purpose: Literal["review", "translation", "triage"]
    roles_answered: int
    roles_total: int
    findings: dict[str, list[dict[str, Any]]]
    confirmed: list[MqmError]
    discarded: list[MqmError]
    score: float | None
    outcome: str  # clean | errors_confirmed | void | winner:<engine>
    winner_target: str | None = None
    usage: Usage = field(default_factory=Usage)
