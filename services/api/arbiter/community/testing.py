"""Qualification tests: a language test and a practical test per language pair.

Both kinds use the same item shape and grading, so admins author them the same way:

    item = {"source": str, "target": str,
            "errors": [{"span", "category", "severity"}],   # expected errors, [] = clean item
            "reference": str | None}                       # the expected fixed target, optional

Language tests use short items that test target-language fluency (grammar, spelling,
register); practical tests use real review situations (accuracy, terminology, tags).

Grading per item (0..1):
    weight(e)  = SEVERITY_WEIGHT[e.severity] (minor 1, major 5, critical 25; neutral counts 1)
    detection  = for items with expected errors: sum of credit over expected errors / sum of weights,
                 credit = weight * 1.0 when a submitted error's span overlaps the expected span,
                          * 0.5 if the category differs, * 0.75 if the severity differs
                 for clean items: max(0, 1 - 0.5 * number of submitted major/critical errors)
                 (false positives on clean text are what makes reviewers expensive)
    similarity = rapidfuzz ratio(submitted target, reference) / 100, when a reference exists
    item       = 0.7 * detection + 0.3 * similarity   (detection alone without a reference)
Test score = 100 * mean(item), unanswered items count 0. Pass = score >= pass_mark and the
answers arrived within time_limit_min (+1 min grace for network); a late submit fails.

A failed test locks the pair's retest for 30 days (ReviewerPair.retest_after). A pair turns
active once every test kind that exists for it (language, practical) has a passed attempt;
the profile then moves candidate -> reviewer and applied -> active.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from arbiter.community import scoring
from arbiter.community.errors import Conflict, Forbidden, Invalid, NotFound
from arbiter.contracts import SEVERITY_WEIGHT
from arbiter.models import ReviewerPair, ReviewerProfile, ReviewerTest, TestAttempt, utcnow

RETEST_DAYS = 30
GRACE = timedelta(minutes=1)
KINDS = ("language", "practical")


# ------------------------------------------------------------------ helpers


def _pairs(session: Session, profile: ReviewerProfile) -> dict[tuple[str, str], ReviewerPair]:
    rows = session.execute(select(ReviewerPair).where(ReviewerPair.reviewer_id == profile.id)).scalars()
    return {(p.source_lang.lower(), p.target_lang.lower()): p for p in rows}


def _attempts(session: Session, profile_id: str, test_id: str) -> list[TestAttempt]:
    return list(
        session.execute(
            select(TestAttempt)
            .where(TestAttempt.reviewer_id == profile_id, TestAttempt.test_id == test_id)
            .order_by(TestAttempt.started_at)
        ).scalars()
    )


def _deadline(test: ReviewerTest, attempt: TestAttempt) -> Any:
    return attempt.started_at + timedelta(minutes=test.time_limit_min)


def _has_passed(session: Session, profile_id: str, test_id: str) -> bool:
    return any(a.passed for a in _attempts(session, profile_id, test_id))


def _tests_for_pair(session: Session, src: str, tgt: str) -> list[ReviewerTest]:
    return list(
        session.execute(
            select(ReviewerTest).where(
                ReviewerTest.active.is_(True),
                ReviewerTest.source_lang == src,
                ReviewerTest.target_lang == tgt,
            )
        ).scalars()
    )


def _status(session: Session, profile: ReviewerProfile, test: ReviewerTest, pair: ReviewerPair) -> str:
    if _has_passed(session, profile.id, test.id):
        return "passed"
    if pair.status in ("locked", "demoted"):
        return "locked"
    now = utcnow()
    attempts = [a for a in _attempts(session, profile.id, test.id) if a.finished_at is not None]
    if attempts and attempts[-1].passed is False and pair.retest_after and pair.retest_after > now:
        return "failed"
    if test.kind == "practical":
        lang_tests = [
            t for t in _tests_for_pair(session, test.source_lang, test.target_lang) if t.kind == "language"
        ]
        if lang_tests and not any(_has_passed(session, profile.id, t.id) for t in lang_tests):
            return "locked"
    return "available"


def test_view(test: ReviewerTest, status: str | None = None, retest_after: Any = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": test.id,
        "kind": test.kind,
        "source_lang": test.source_lang,
        "target_lang": test.target_lang,
        "domain": test.domain,
        "time_limit_min": test.time_limit_min,
        "pass_mark": test.pass_mark,
        "item_count": len(test.items or []),
    }
    if status is not None:
        out["status"] = status
        out["retest_after"] = retest_after.isoformat() if retest_after and status == "failed" else None
    return out


# ------------------------------------------------------------------ public API


def available_tests(session: Session, profile: ReviewerProfile) -> list[dict[str, Any]]:
    """GET /reviewer/tests: every active test for the reviewer's pairs with a status."""
    pairs = _pairs(session, profile)
    out: list[dict[str, Any]] = []
    tests = session.execute(
        select(ReviewerTest).where(ReviewerTest.active.is_(True)).order_by(ReviewerTest.created_at)
    ).scalars()
    for test in tests:
        pair = pairs.get((test.source_lang.lower(), test.target_lang.lower()))
        if pair is None:
            continue
        status = _status(session, profile, test, pair)
        out.append(test_view(test, status, pair.retest_after))
    out.sort(
        key=lambda t: (
            t["source_lang"],
            t["target_lang"],
            KINDS.index(t["kind"]) if t["kind"] in KINDS else 9,
        )
    )
    return out


def start(session: Session, profile: ReviewerProfile, test_id: str) -> dict[str, Any]:
    """Start (or resume, while time remains) an attempt. Items are sent without answer keys."""
    test = session.get(ReviewerTest, test_id)
    if test is None or not test.active:
        raise NotFound("test not found")
    pair = _pairs(session, profile).get((test.source_lang.lower(), test.target_lang.lower()))
    if pair is None:
        raise Forbidden("this test is not for one of your language pairs")
    now = utcnow()
    # An open attempt: resume it while time remains, otherwise close it as a fail.
    for att in _attempts(session, profile.id, test.id):
        if att.finished_at is None:
            if now <= _deadline(test, att):
                return _attempt_payload(test, att)
            _finish(session, profile, test, pair, att, score=0.0, passed=False)
    status = _status(session, profile, test, pair)
    if status != "available":
        raise Conflict(f"test is {status}", {"status": status})
    att = TestAttempt(test_id=test.id, reviewer_id=profile.id, answers=[], started_at=now)
    session.add(att)
    session.flush()
    return _attempt_payload(test, att)


def _attempt_payload(test: ReviewerTest, att: TestAttempt) -> dict[str, Any]:
    return {
        "attempt_id": att.id,
        "test_id": test.id,
        "kind": test.kind,
        "items": [
            {"index": i, "source": it.get("source", ""), "target": it.get("target", "")}
            for i, it in enumerate(test.items or [])
        ],
        "time_limit_min": test.time_limit_min,
        "expires_at": _deadline(test, att).isoformat(),
    }


def _overlaps(a: str, b: str) -> bool:
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    if not a or not b:
        return False
    return a in b or b in a or fuzz.ratio(a, b) >= 80


def _weight(severity: str) -> float:
    return float(max(1, SEVERITY_WEIGHT.get(severity, 1)))


def grade_item(item: dict[str, Any], answer: dict[str, Any] | None) -> float:
    """Score one item 0..1 (formula in the module docstring)."""
    if answer is None:
        return 0.0
    expected = item.get("errors") or []
    submitted = [e for e in (answer.get("errors") or []) if isinstance(e, dict)]
    if expected:
        total = sum(_weight(e.get("severity", "minor")) for e in expected)
        got = 0.0
        used: set[int] = set()
        for exp in expected:
            best = 0.0
            best_j = -1
            for j, sub in enumerate(submitted):
                if j in used or not _overlaps(exp.get("span", ""), sub.get("span", "")):
                    continue
                credit = 1.0
                if (sub.get("category") or sub.get("dimension")) != exp.get("category"):
                    credit *= 0.5
                if sub.get("severity") != exp.get("severity"):
                    credit *= 0.75
                if credit > best:
                    best, best_j = credit, j
            if best_j >= 0:
                used.add(best_j)
                got += best * _weight(exp.get("severity", "minor"))
        detection = got / total if total else 1.0
    else:
        false_pos = sum(1 for e in submitted if e.get("severity") in ("major", "critical"))
        detection = max(0.0, 1.0 - 0.5 * false_pos)
    reference = item.get("reference")
    if reference:
        target = answer.get("target")
        if not isinstance(target, str):
            target = item.get("target", "")
        similarity = fuzz.ratio(target, reference) / 100.0
        return 0.7 * detection + 0.3 * similarity
    return detection


def _finish(
    session: Session,
    profile: ReviewerProfile,
    test: ReviewerTest,
    pair: ReviewerPair,
    att: TestAttempt,
    *,
    score: float,
    passed: bool,
) -> None:
    att.score = round(score, 2)
    att.passed = passed
    att.finished_at = utcnow()
    if passed:
        _maybe_activate(session, profile, pair)
    else:
        pair.retest_after = att.finished_at + timedelta(days=RETEST_DAYS)
    session.flush()


def _maybe_activate(session: Session, profile: ReviewerProfile, pair: ReviewerPair) -> None:
    tests = _tests_for_pair(session, pair.source_lang, pair.target_lang)
    kinds = {t.kind for t in tests}
    if not kinds:
        return
    for kind in kinds:
        if not any(_has_passed(session, profile.id, t.id) for t in tests if t.kind == kind):
            return
    if pair.status in ("testing", "locked"):
        pair.status = "active"
        pair.retest_after = None
        if not pair.control_seen:
            pair.score = scoring.compute([])
    if profile.level == "candidate":
        profile.level = "reviewer"
    if profile.status == "applied":
        profile.status = "active"
    if not profile.score:
        profile.score = scoring.compute([])


def grade(
    session: Session, profile: ReviewerProfile, attempt_id: str, answers: list[dict[str, Any]]
) -> dict[str, Any]:
    """POST /reviewer/attempts/{id}/submit -> {score, passed}."""
    att = session.get(TestAttempt, attempt_id, with_for_update=True)
    if att is None or att.reviewer_id != profile.id:
        raise NotFound("attempt not found")
    if att.finished_at is not None:
        raise Conflict("attempt already submitted")
    test = session.get(ReviewerTest, att.test_id)
    assert test is not None
    pair = _pairs(session, profile).get((test.source_lang.lower(), test.target_lang.lower()))
    if pair is None:
        raise Forbidden("this test is not for one of your language pairs")
    if not isinstance(answers, list):
        raise Invalid("answers must be a list")
    by_index: dict[int, dict[str, Any]] = {}
    for a in answers:
        if isinstance(a, dict) and isinstance(a.get("index"), int):
            by_index[a["index"]] = a
    items = test.items or []
    scores = [grade_item(it, by_index.get(i)) for i, it in enumerate(items)]
    score = 100.0 * sum(scores) / len(scores) if scores else 0.0
    late = utcnow() > _deadline(test, att) + GRACE
    passed = (not late) and score >= test.pass_mark
    att.answers = [by_index[i] for i in sorted(by_index)]
    _finish(session, profile, test, pair, att, score=score, passed=passed)
    out: dict[str, Any] = {"score": round(score, 2), "passed": passed}
    if late:
        out["late"] = True
    return out


# ------------------------------------------------------------------ admin + seed


def create_test(session: Session, data: dict[str, Any]) -> dict[str, Any]:
    """POST /admin/tests."""
    kind = data.get("kind")
    if kind not in KINDS:
        raise Invalid("kind must be language or practical")
    items = data.get("items") or []
    if not isinstance(items, list) or not items:
        raise Invalid("items must be a non-empty list")
    for it in items:
        if not isinstance(it, dict) or "source" not in it or "target" not in it:
            raise Invalid("every item needs source and target")
    test = ReviewerTest(
        kind=kind,
        source_lang=str(data["source_lang"]).lower(),
        target_lang=str(data["target_lang"]).lower(),
        domain=data.get("domain", "general"),
        items=items,
        pass_mark=float(data.get("pass_mark", 80.0)),
        time_limit_min=int(data.get("time_limit_min", 45)),
        active=bool(data.get("active", True)),
    )
    session.add(test)
    session.flush()
    return test_view(test)


DEMO_NOTE = "DEMO content: fictional sample sentences for development, replace before launch."

_DEMO: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = {
    ("en", "sr"): {
        "language": [
            {
                "source": "Your order has been shipped.",
                "target": "Vaša porudžbina je poslata.",
                "errors": [],
                "reference": "Vaša porudžbina je poslata.",
            },
            {
                "source": "The files were uploaded.",
                "target": "Fajlovi je otpremljeni.",
                "errors": [{"span": "je", "category": "fluency", "severity": "major"}],
                "reference": "Fajlovi su otpremljeni.",
            },
        ],
        "practical": [
            {
                "source": "Save your changes before closing the window.",
                "target": "Sačuvajte izmene posle zatvaranja prozora.",
                "errors": [{"span": "posle", "category": "accuracy", "severity": "major"}],
                "reference": "Sačuvajte izmene pre zatvaranja prozora.",
            },
            {
                "source": "Click ⟦1⟧Next⟦/1⟧ to continue.",
                "target": "Kliknite na ⟦1⟧Dalje⟦/1⟧ da biste nastavili.",
                "errors": [],
                "reference": "Kliknite na ⟦1⟧Dalje⟦/1⟧ da biste nastavili.",
            },
        ],
    },
    ("en", "de"): {
        "language": [
            {
                "source": "Your order has been shipped.",
                "target": "Ihre Bestellung wurde versandt.",
                "errors": [],
                "reference": "Ihre Bestellung wurde versandt.",
            },
            {
                "source": "The files were uploaded.",
                "target": "Die Dateien wurde hochgeladen.",
                "errors": [{"span": "wurde", "category": "fluency", "severity": "major"}],
                "reference": "Die Dateien wurden hochgeladen.",
            },
        ],
        "practical": [
            {
                "source": "Save your changes before closing the window.",
                "target": "Speichern Sie Ihre Änderungen, nachdem Sie das Fenster schließen.",
                "errors": [{"span": "nachdem", "category": "accuracy", "severity": "major"}],
                "reference": "Speichern Sie Ihre Änderungen, bevor Sie das Fenster schließen.",
            },
            {
                "source": "Click ⟦1⟧Next⟦/1⟧ to continue.",
                "target": "Klicken Sie auf ⟦1⟧Weiter⟦/1⟧, um fortzufahren.",
                "errors": [],
                "reference": "Klicken Sie auf ⟦1⟧Weiter⟦/1⟧, um fortzufahren.",
            },
        ],
    },
}


def seed_default_tests(session: Session) -> list[ReviewerTest]:
    """Create the DEMO test set for en->sr and en->de (idempotent). Fictional sample content."""
    created: list[ReviewerTest] = []
    for (src, tgt), kinds in _DEMO.items():
        for kind, items in kinds.items():
            exists = session.execute(
                select(ReviewerTest.id).where(
                    ReviewerTest.kind == kind,
                    ReviewerTest.source_lang == src,
                    ReviewerTest.target_lang == tgt,
                    ReviewerTest.domain == "demo",
                )
            ).first()
            if exists:
                continue
            test = ReviewerTest(
                kind=kind,
                source_lang=src,
                target_lang=tgt,
                domain="demo",
                items=[{**it, "note": DEMO_NOTE} for it in items],
                pass_mark=80.0,
                time_limit_min=30 if kind == "language" else 45,
                active=True,
            )
            session.add(test)
            created.append(test)
    session.flush()
    return created
