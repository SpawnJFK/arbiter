"""SQLAlchemy models. Importing this package registers every table on Base.metadata."""

from arbiter.models.assets import Glossary, StyleCard, Term, TermQuestion, TmEntry
from arbiter.models.common import new_id, utcnow
from arbiter.models.content import FileAsset, Job, Project, Segment
from arbiter.models.integrations import IdempotencyRecord, Webhook, WebhookDelivery, WorkItem
from arbiter.models.money import Invoice, LedgerEntry, Payout, Quote, UsageRecord
from arbiter.models.provenance import ProvenanceEvent
from arbiter.models.quality import (
    ControlSample,
    EngineScore,
    EscapedError,
    QualityMetric,
    SenateRun,
    Threshold,
)
from arbiter.models.reviewers import (
    Dispute,
    ReviewerPair,
    ReviewerProfile,
    ReviewerScoreEvent,
    ReviewerTest,
    ReviewTask,
    TestAttempt,
)
from arbiter.models.tenancy import ApiKey, Organization, User

__all__ = [
    "ApiKey",
    "ControlSample",
    "Dispute",
    "EngineScore",
    "EscapedError",
    "FileAsset",
    "Glossary",
    "IdempotencyRecord",
    "Invoice",
    "Job",
    "LedgerEntry",
    "Organization",
    "Payout",
    "Project",
    "ProvenanceEvent",
    "QualityMetric",
    "Quote",
    "ReviewTask",
    "ReviewerPair",
    "ReviewerProfile",
    "ReviewerScoreEvent",
    "ReviewerTest",
    "Segment",
    "SenateRun",
    "StyleCard",
    "Term",
    "TermQuestion",
    "TestAttempt",
    "Threshold",
    "TmEntry",
    "UsageRecord",
    "User",
    "Webhook",
    "WebhookDelivery",
    "WorkItem",
    "new_id",
    "utcnow",
]
