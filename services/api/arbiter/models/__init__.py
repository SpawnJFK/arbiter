"""SQLAlchemy models. Importing this package registers every table on Base.metadata."""

from arbiter.models.agency import (
    AssistantMessage,
    AssistantThread,
    CrmAccount,
    CrmActivity,
    CrmContact,
    CrmDeal,
    Dashboard,
    PriceList,
    WorkflowTemplate,
)
from arbiter.models.assets import Glossary, StyleCard, Term, TermQuestion, TmEntry
from arbiter.models.common import new_id, utcnow
from arbiter.models.content import FileAsset, Job, Project, Segment
from arbiter.models.engines import CustomModel, EngineBudget, EngineCredential, EngineRoute, TrainingJob
from arbiter.models.i18n import UiLocale, UiMessage
from arbiter.models.integrations import IdempotencyRecord, Webhook, WebhookDelivery, WorkItem
from arbiter.models.money import Invoice, LedgerEntry, Payout, Quote, UsageRecord
from arbiter.models.ops import AccountToken, EmailMessage, UploadSession
from arbiter.models.platform import AuditEvent, Role, SsoConfig, SsoDomain, SsoState, UserInvite
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
from arbiter.models.strings import (
    StringBatch,
    StringBranch,
    StringHistory,
    StringKey,
    StringProject,
    StringRelease,
    StringTranslation,
)
from arbiter.models.tenancy import ApiKey, Organization, User

__all__ = [
    "AccountToken",
    "ApiKey",
    "AssistantMessage",
    "AssistantThread",
    "AuditEvent",
    "CrmAccount",
    "CrmActivity",
    "CrmContact",
    "CrmDeal",
    "Dashboard",
    "PriceList",
    "WorkflowTemplate",
    "ControlSample",
    "CustomModel",
    "EngineBudget",
    "EngineCredential",
    "EngineRoute",
    "TrainingJob",
    "Dispute",
    "EmailMessage",
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
    "Role",
    "SsoConfig",
    "SsoDomain",
    "SsoState",
    "ReviewerPair",
    "ReviewerProfile",
    "ReviewerScoreEvent",
    "ReviewerTest",
    "Segment",
    "SenateRun",
    "StringBatch",
    "StringBranch",
    "StringHistory",
    "StringKey",
    "StringProject",
    "StringRelease",
    "StringTranslation",
    "StyleCard",
    "Term",
    "TermQuestion",
    "TestAttempt",
    "Threshold",
    "TmEntry",
    "UiLocale",
    "UploadSession",
    "UiMessage",
    "UsageRecord",
    "User",
    "UserInvite",
    "Webhook",
    "WebhookDelivery",
    "WorkItem",
    "new_id",
    "utcnow",
]
