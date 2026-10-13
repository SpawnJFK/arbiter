"""Software string localization (module `strings`, migration 0007).

A string project holds keys (identified by namespace + name) and their values per language;
the base language value is a translation row like any other. Branches are copy-on-write:
the `main` branch is a real row created with the project, and a translation row with
branch_id = <feature branch> overrides the main row for that key and language only inside
the branch. Keys created in a branch belong to it until the branch is merged. Merge applies
branch rows whose main counterpart did not change since they were copied (base_version);
otherwise it reports a conflict for the user to resolve (D-051).

string_history is append-only (trigger below), the strings counterpart of provenance_events.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from arbiter.db import Base
from arbiter.models.common import created_at_column, id_column, utcnow

STRING_HISTORY_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION string_history_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'string_history is append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS string_history_no_update ON string_history;
CREATE TRIGGER string_history_no_update
    BEFORE UPDATE OR DELETE ON string_history
    FOR EACH ROW EXECUTE FUNCTION string_history_append_only();
"""


class StringProject(Base):
    __tablename__ = "string_projects"

    id: Mapped[str] = id_column("spj")
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    # Opaque id used in public OTA URLs (never the internal id, never guessable).
    public_id: Mapped[str] = mapped_column(String(40), unique=True)
    base_lang: Mapped[str] = mapped_column(String(16))
    target_langs: Mapped[list[str]] = mapped_column(JSON, default=list)
    platforms: Mapped[list[str]] = mapped_column(
        JSON, default=list
    )  # web | ios | android | flutter | backend
    tier: Mapped[str] = mapped_column(String(20), default="hybrid")
    # placeholder_style, plural_rules, human_review, release_min_state, fallback_to_base,
    # private, distribution_token_hash, default_format, engine
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StringBranch(Base):
    __tablename__ = "string_branches"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    id: Mapped[str] = id_column("sbr")
    project_id: Mapped[str] = mapped_column(ForeignKey("string_projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    from_branch_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_main: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    merged_by: Mapped[str | None] = mapped_column(String(40), nullable=True)


class StringKey(Base):
    __tablename__ = "string_keys"
    __table_args__ = (
        UniqueConstraint("project_id", "namespace", "name"),
        Index("ix_string_keys_project_branch", "project_id", "branch_id"),
    )

    id: Mapped[str] = id_column("skey")
    project_id: Mapped[str] = mapped_column(ForeignKey("string_projects.id", ondelete="CASCADE"))
    # The branch the key was created in (main for most keys); visible only there until merged.
    branch_id: Mapped[str] = mapped_column(ForeignKey("string_branches.id", ondelete="CASCADE"))
    namespace: Mapped[str] = mapped_column(String(200), default="")  # file / module, "" = default
    name: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(10), default="string")  # string | plural | array
    description: Mapped[str] = mapped_column(Text, default="")  # context for translators
    screenshot_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    max_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    translatable: Mapped[bool] = mapped_column(Boolean, default=True)
    # Format details kept for a faithful export (ICU argument name, PO msgctxt, ARB placeholders).
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StringTranslation(Base):
    __tablename__ = "string_translations"
    __table_args__ = (
        UniqueConstraint("key_id", "branch_id", "lang"),
        Index("ix_string_tr_branch_lang", "branch_id", "lang"),
    )

    id: Mapped[str] = id_column("str")
    key_id: Mapped[str] = mapped_column(ForeignKey("string_keys.id", ondelete="CASCADE"))
    branch_id: Mapped[str] = mapped_column(ForeignKey("string_branches.id", ondelete="CASCADE"))
    lang: Mapped[str] = mapped_column(String(16))
    value: Mapped[str] = mapped_column(Text, default="")  # string kind ("" for plural/array)
    forms: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)  # plural / array forms
    state: Mapped[str] = mapped_column(String(16), default="untranslated")
    origin: Mapped[str | None] = mapped_column(String(20), nullable=True)  # import | human | tm | mt | review
    engine: Mapped[str | None] = mapped_column(String(80), nullable=True)
    qe_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    qa: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)  # last hard QA issues
    # blocking QA issue: never shipped in a release (the app falls back to the base language)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    review_task_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    # Branch rows: version of the main row when the branch copy was made (0 = main had none).
    base_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StringHistory(Base):
    __tablename__ = "string_history"
    __table_args__ = (Index("ix_string_history_key", "key_id", "lang", "at"),)

    id: Mapped[str] = id_column("shi")
    org_id: Mapped[str] = mapped_column(String(40), index=True)
    project_id: Mapped[str] = mapped_column(String(40))
    key_id: Mapped[str] = mapped_column(String(40))  # no FK: history outlives deleted keys
    branch_id: Mapped[str] = mapped_column(String(40))
    lang: Mapped[str] = mapped_column(String(16), default="")
    # created | edited | imported | machine | tm | qe | approved | cleared | reviewed | merged |
    # source_changed | archived | restored | key_updated
    event: Mapped[str] = mapped_column(String(30))
    version: Mapped[int] = mapped_column(Integer, default=0)
    value: Mapped[str] = mapped_column(Text, default="")
    forms: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)
    state: Mapped[str] = mapped_column(String(16), default="")
    actor_type: Mapped[str] = mapped_column(String(10), default="system")  # human | engine | system
    actor_id: Mapped[str] = mapped_column(String(120), default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = created_at_column()


class StringRelease(Base):
    __tablename__ = "string_releases"
    __table_args__ = (UniqueConstraint("project_id", "version_label"),)

    id: Mapped[str] = id_column("srl")
    project_id: Mapped[str] = mapped_column(ForeignKey("string_projects.id", ondelete="CASCADE"), index=True)
    branch_id: Mapped[str] = mapped_column(String(40))
    version_label: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | published
    langs: Mapped[list[str]] = mapped_column(JSON, default=list)
    # {lang: {"json": {"key": storage key, "sha256": ..., "bytes": n}, "<format>": {...}}}
    bundles: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64))
    key_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StringBatch(Base):
    """One "translate missing" / "pre-translate from TM" run, processed by the worker in chunks."""

    __tablename__ = "string_batches"

    id: Mapped[str] = id_column("sbt")
    project_id: Mapped[str] = mapped_column(ForeignKey("string_projects.id", ondelete="CASCADE"), index=True)
    branch_id: Mapped[str] = mapped_column(String(40))
    langs: Mapped[list[str]] = mapped_column(JSON, default=list)
    mode: Mapped[str] = mapped_column(String(16), default="translate")  # translate | tm_only
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued | running | done | failed
    total: Mapped[int] = mapped_column(Integer, default=0)
    done: Mapped[int] = mapped_column(Integer, default=0)
    # {tm, machine, reviewed, blocked, review_tasks, skipped, failed}
    counts: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    items: Mapped[list[list[str]]] = mapped_column(JSON, default=list)  # [[key_id, lang], ...] to do
    review_job_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
