"""Operator command line: `python -m arbiter.cli <command>`.

Commands:
  create-admin --email E --password P   platform operator account (role admin, no org)
  seed-demo [--password P]              idempotent DEMO data for local development
  run-worker                            the pipeline worker (same as python -m arbiter.pipeline.worker)
  calibrate [--dry-run]                 weekly threshold calibration from control samples

Everything seed-demo creates is fictional sample data under the .test domain, for
development and demos only. It never runs implicitly.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from arbiter import db as dbmod
from arbiter.api import security
from arbiter.community import profiles, scoring, testing
from arbiter.config import get_settings
from arbiter.linguistic import glossary as glossary_mod
from arbiter.models import (
    ControlSample,
    Glossary,
    Job,
    Organization,
    ReviewerPair,
    Term,
    Threshold,
    User,
    utcnow,
)
from arbiter.quality.calibration import propose_threshold

DEMO_PASSWORD = "demo-password-123"
DEMO_ORG_NAME = "Demo Co"
DEMO_ORG_SLUG = "demo-co"
DEMO_GLOSSARY = "Demo glossary (fictional sample terms)"
DEMO_PAIRS = (("en", "sr"), ("en", "de"))
# (source_lang, target_lang, source_term, target_term, kind, note)
DEMO_TERMS: tuple[tuple[str, str, str, str | None, str, str], ...] = (
    ("en", "sr", "invoice", "faktura", "mandatory", ""),
    ("en", "sr", "settings", "podešavanja", "mandatory", ""),
    ("en", "sr", "file", "fajl", "forbidden", "use 'datoteka'"),
    ("en", "sr", "Demo Co", None, "do_not_translate", "company name"),
    ("en", "de", "invoice", "Rechnung", "mandatory", ""),
    ("en", "de", "settings", "Einstellungen", "mandatory", ""),
    ("en", "de", "file", "File", "forbidden", "use 'Datei'"),
    ("en", "de", "Demo Co", None, "do_not_translate", "company name"),
)
CALIBRATION_WINDOW_DAYS = 30
CALIBRATION_MIN_SAMPLES = 200
CALIBRATION_LOG_KEEP = 100


# ------------------------------------------------------------------ create-admin


def create_admin(session: Session, email: str, password: str) -> tuple[User, bool]:
    """Create (or reset the password of) a platform admin. Returns (user, created)."""
    email_n = email.strip().lower()
    if "@" not in email_n:
        raise ValueError("invalid email")
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    user = session.execute(select(User).where(User.email == email_n)).scalar_one_or_none()
    if user is not None:
        if user.role != "admin":
            raise ValueError(f"{email_n} already exists with role {user.role}")
        user.password_hash = security.hash_password(password)
        session.flush()
        return user, False
    user = User(
        email=email_n,
        name="Platform admin",
        password_hash=security.hash_password(password),
        role="admin",
        org_id=None,
    )
    session.add(user)
    session.flush()
    return user, True


# ------------------------------------------------------------------ seed-demo


def _user(session: Session, email: str, **fields: Any) -> tuple[User, bool]:
    user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is not None:
        return user, False
    user = User(email=email, **fields)
    session.add(user)
    session.flush()
    return user, True


def seed_demo(session: Session, password: str = DEMO_PASSWORD) -> dict[str, Any]:
    """Create the DEMO dataset. Idempotent: existing rows are found by email/slug/name and kept."""
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    created: list[str] = []
    pw_hash = security.hash_password(password)

    org = session.execute(select(Organization).where(Organization.slug == DEMO_ORG_SLUG)).scalar_one_or_none()
    if org is None:
        org = Organization(
            name=DEMO_ORG_NAME,
            slug=DEMO_ORG_SLUG,
            vertical="software",
            ai_subprocessors_opt_in=True,
            settings={"demo": True},
        )
        session.add(org)
        session.flush()
        created.append(f"org {DEMO_ORG_NAME}")

    for email, name, role in (
        ("pm@demo.test", "Demo PM", "pm"),
        ("client@demo.test", "Demo Client", "client"),
    ):
        _, new = _user(session, email, name=name, password_hash=pw_hash, role=role, org_id=org.id)
        if new:
            created.append(f"{role} {email}")

    _, new = _user(
        session, "admin@demo.test", name="Demo Admin", password_hash=pw_hash, role="admin", org_id=None
    )
    if new:
        created.append("admin admin@demo.test")

    created += [
        f"test {t.kind} {t.source_lang}->{t.target_lang}" for t in testing.seed_default_tests(session)
    ]

    reviewer_user = session.execute(
        select(User).where(User.email == "reviewer@demo.test")
    ).scalar_one_or_none()
    if reviewer_user is None:
        reviewer_user, profile = profiles.apply(
            session,
            name="Demo Reviewer",
            email="reviewer@demo.test",
            password=password,
            country="RS",
            pairs=list(DEMO_PAIRS),
            domains=["software"],
        )
        created.append("reviewer reviewer@demo.test")
    else:
        profile = profiles.profile_for_user(session, reviewer_user.id)
    # Demo reviewer skips the tests: active for both pairs, fictional tax info.
    profile.status = "active"
    if profile.level == "candidate":
        profile.level = "reviewer"
    if not profile.score:
        profile.score = scoring.compute([])
    for pair in session.execute(select(ReviewerPair).where(ReviewerPair.reviewer_id == profile.id)).scalars():
        if pair.status != "active":
            pair.status = "active"
            pair.retest_after = None
            pair.score = pair.score or scoring.compute([])
    if not profiles.tax_info_complete(profile):
        profiles.update_tax_info(
            session,
            profile,
            legal_name="Demo Reviewer",
            tax_id="DEMO-0000",
            address="1 Demo Street, Demo City",
            date_of_birth="1990-01-01",
            payout_method="sepa",
            payout_details={"iban": "DEMO-NOT-A-REAL-ACCOUNT"},
        )

    gl = session.execute(
        select(Glossary).where(Glossary.org_id == org.id, Glossary.name == DEMO_GLOSSARY)
    ).scalar_one_or_none()
    if gl is None:
        gl = glossary_mod.create_glossary(session, org.id, DEMO_GLOSSARY)
        created.append("glossary")
    existing = {
        (t.source_lang, t.target_lang, t.source_term, t.kind)
        for t in session.execute(
            select(Term).where(Term.glossary_id == gl.id, Term.valid_to.is_(None))
        ).scalars()
    }
    for src, tgt, s_term, t_term, kind, note in DEMO_TERMS:
        if (src, tgt, s_term, kind) in existing:
            continue
        glossary_mod.add_term(session, gl.id, src, tgt, s_term, t_term, kind, note=note)
        created.append(f"term {src}->{tgt} {s_term} ({kind})")

    session.flush()
    return {
        "org_id": org.id,
        "reviewer_id": profile.id,
        "glossary_id": gl.id,
        "created": created,
        "logins": ["pm@demo.test", "client@demo.test", "reviewer@demo.test", "admin@demo.test"],
    }


# ------------------------------------------------------------------ calibrate


def _samples(session: Session, thr: Threshold, since: datetime) -> list[tuple[float, bool]]:
    stmt = (
        select(ControlSample.qe_score, ControlSample.verdict)
        .join(Job, Job.id == ControlSample.job_id)
        .where(
            ControlSample.org_id == thr.org_id,
            Job.content_type == thr.content_type,
            ControlSample.verdict.is_not(None),
            ControlSample.decided_at >= since,
        )
    )
    if thr.target_lang is not None:
        stmt = stmt.where(Job.target_lang == thr.target_lang)
    else:
        # The default row covers languages without their own threshold row.
        specific = select(Threshold.target_lang).where(
            Threshold.org_id == thr.org_id,
            Threshold.content_type == thr.content_type,
            Threshold.target_lang.is_not(None),
        )
        stmt = stmt.where(Job.target_lang.not_in(specific))
    return [(float(score), verdict == "escaped") for score, verdict in session.execute(stmt).all()]


def calibrate(
    session: Session, *, now: datetime | None = None, dry_run: bool = False
) -> list[dict[str, Any]]:
    """Propose and apply a new value for every threshold with enough recent control samples.

    D-011: at most `max_threshold_step_per_week` per week, so a threshold calibrated less
    than 7 days ago is skipped. The reason is kept in the org settings under
    "calibration_log" (newest last) and the threshold's last_calibrated_at is set.
    """
    settings = get_settings()
    now = now or utcnow()
    since = now - timedelta(days=CALIBRATION_WINDOW_DAYS)
    rows: list[dict[str, Any]] = []
    thresholds = session.execute(
        select(Threshold).order_by(Threshold.org_id, Threshold.content_type, Threshold.target_lang)
    ).scalars()
    for thr in thresholds:
        samples = _samples(session, thr, since)
        row: dict[str, Any] = {
            "threshold_id": thr.id,
            "org_id": thr.org_id,
            "content_type": thr.content_type,
            "target_lang": thr.target_lang or "*",
            "samples": len(samples),
            "old": thr.value,
            "new": thr.value,
            "applied": False,
        }
        if len(samples) < CALIBRATION_MIN_SAMPLES:
            row["reason"] = f"skipped: {len(samples)} samples < {CALIBRATION_MIN_SAMPLES}"
            rows.append(row)
            continue
        if thr.last_calibrated_at is not None and now - thr.last_calibrated_at < timedelta(days=7):
            row["reason"] = "skipped: calibrated less than 7 days ago"
            rows.append(row)
            continue
        new, reason = propose_threshold(
            thr.value,
            samples,
            target_escaped_rate=settings.escaped_error_target,
            max_step=settings.max_threshold_step_per_week,
            min_samples=CALIBRATION_MIN_SAMPLES,
        )
        row["new"], row["reason"] = new, reason
        if not dry_run:
            thr.value = new
            thr.last_calibrated_at = now
            org = session.get(Organization, thr.org_id)
            if org is not None:
                cfg = dict(org.settings or {})
                log = list(cfg.get("calibration_log") or [])
                log.append(
                    {
                        "at": now.isoformat(),
                        "threshold_id": thr.id,
                        "content_type": thr.content_type,
                        "target_lang": thr.target_lang,
                        "old": row["old"],
                        "new": new,
                        "samples": len(samples),
                        "reason": reason,
                    }
                )
                cfg["calibration_log"] = log[-CALIBRATION_LOG_KEEP:]
                org.settings = cfg  # reassign: JSON columns do not track in-place mutation
            row["applied"] = True
        rows.append(row)
    session.flush()
    return rows


def _print_table(rows: list[dict[str, Any]]) -> None:
    cols = ("org_id", "content_type", "target_lang", "samples", "old", "new", "applied", "reason")
    data = [[str(r[c]) for c in cols] for r in rows]
    widths = [max(len(c), *(len(d[i]) for d in data)) if data else len(c) for i, c in enumerate(cols)]
    print("  ".join(c.ljust(w) for c, w in zip(cols, widths, strict=True)))
    print("  ".join("-" * w for w in widths))
    for d in data:
        print("  ".join(v.ljust(w) for v, w in zip(d, widths, strict=True)))
    if not rows:
        print("(no thresholds)")


# ------------------------------------------------------------------ entry point


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m arbiter.cli", description="Arbiter operator commands")
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("create-admin", help="create or reset a platform admin account")
    a.add_argument("--email", required=True)
    a.add_argument("--password", required=True)
    s = sub.add_parser("seed-demo", help="create fictional demo data (idempotent)")
    s.add_argument("--password", default=DEMO_PASSWORD, help=f"password for all demo users ({DEMO_PASSWORD})")
    sub.add_parser("run-worker", help="run the pipeline worker")
    c = sub.add_parser("calibrate", help="calibrate auto-approval thresholds from control samples")
    c.add_argument("--dry-run", action="store_true", help="print proposals without saving")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "run-worker":
        from arbiter.pipeline.worker import main as worker_main

        worker_main()
        return 0

    session = dbmod.session_factory()()
    try:
        if args.command == "create-admin":
            user, new = create_admin(session, args.email, args.password)
            print(f"{'created' if new else 'password reset for'} admin {user.email} ({user.id})")
        elif args.command == "seed-demo":
            out = seed_demo(session, args.password)
            print(f"demo org {DEMO_ORG_NAME} ({out['org_id']}); DEMO data, fictional")
            for line in out["created"] or ["nothing new: demo data already present"]:
                print(f"  + {line}")
            print(f"logins: {', '.join(out['logins'])} (password: {args.password})")
        elif args.command == "calibrate":
            _print_table(calibrate(session, dry_run=args.dry_run))
        if getattr(args, "dry_run", False):
            session.rollback()
        else:
            session.commit()
    except ValueError as e:
        session.rollback()
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
