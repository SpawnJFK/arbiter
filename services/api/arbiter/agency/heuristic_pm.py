"""Deterministic PM copilot planner (module pm): the assistant's brain for project-management
questions when the LLM is a mock or unavailable.

parse_pm() recognises four questions, in English and Serbian (latin, with or without
diacritics). arbiter.agency.copilot computes the answer from the database (capacity planner,
deadline risk, assignment suggestions, price lists) and pm_answer() turns that result into the
reply and the plan. Plan actions (create_assignment, draft_quote) are applied by a human, like
every other plan action. Output is English (English-first); other locales get the same note
as the setup planner.

  capacity            "who is free for EN->DE 20k words by Friday",
                      "ko je slobodan za engleski na nemacki 20.000 reci do petka"
  risk                "which jobs are at risk", "koji poslovi su u riziku", "sta nece stici"
  propose_assignment  "propose assignments for job job_01...", "predlozi dodelu za posao Launch"
  draft_quote         "draft a quote for Acme: 5000 words en>de", "napravi ponudu za Acme ..."
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from arbiter.agency.heuristic import LANGS, _lang_hint, _localized, _tier_hint, fold

WEEKDAYS: dict[str, int] = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
    "ponedelj": 0, "utor": 1, "sred": 2, "cetvrt": 3, "petk": 4, "petak": 4, "subot": 5, "nedelj": 6,
}  # fmt: skip
PM_CAPACITY = re.compile(
    r"\bwho\b[^.?!]{0,40}\b(?:is\s+|are\s+)?(?:free|available|has\s+(?:the\s+)?capacity|can\s+(?:take|do|handle))"
    r"|\b(?:free|available)\s+(?:vendors?|translators?|linguists?|reviewers?|people)"
    r"|\bcapacity\s+(?:for|planner)"
    r"|\bko\s+(?:je\s+|su\s+)?(?:slobod\w*|dostup\w*|ima\s+(?:vremena|kapacitet\w*)|moze\s+da\s+(?:preuzme|uradi)|stize)"
    r"|\bslobodn\w*\s+(?:prevodi\w*|lektor\w*|revizor\w*|vendor\w*|saradni\w*)|\bkapacitet\w*\s+za\b"
)
PM_RISK = re.compile(
    r"\bat\s+risk\b|\brisky\b|\b(?:deadline|delivery)\s+risk|\bwill\s+miss\b"
    r"|\bmiss\w*\s+(?:the\s+|their\s+|its\s+)?deadline|\bwon'?t\s+make\b"
    r"|\bu\s+riziku\b|\brizik\w*|\bugrozen\w*|\bnece\s+stici|\bnecemo\s+stici|\bkasnice\b|\bprobice\b"
)
PM_ASSIGN = re.compile(
    r"\b(?:propose|suggest|recommend)\w*\b[^.?!]{0,40}\b(?:assign\w*|vendors?|translators?|linguists?|reviewers?|who)\b"
    r"|\bassign(?:ment)?s?\s+for\b|\bwho\s+should\s+(?:do|take|review|translate)"
    r"|\bpredl\w*\b[^.?!]{0,40}\b(?:dodel\w*|prevodi\w*|lektor\w*|revizor\w*|vendor\w*|ko\b)"
    r"|\bdodel\w*\s+(?:za\s+)?pos\w*|\bko\s+da\s+radi\b"
)
PM_QUOTE = re.compile(
    r"\b(?:draft|prepare|make|create|write)\b[^.?!]{0,30}\b(?:quote|estimate|proposal)\b|\bquote\s+for\b"
    r"|\b(?:napravi|pripremi|sastavi|izradi)\w*\b[^.?!]{0,30}\b(?:ponud\w*|predracun\w*|kalkulacij\w*)"
    r"|\bponud\w*\s+za\b"
)
WORDS_RE = re.compile(
    r"(\d{1,3}(?:[ .,]\d{3})+|\d+(?:[.,]\d+)?)\s*(k\b|hiljad\w*|thousand)?\s*(?:words?|reci|rec)\b"
)
JOB_ID_RE = re.compile(r"\bjob_[0-9a-z]{26}\b")
_LANG_ALT = "|".join(sorted(LANGS, key=len, reverse=True))
LANG_WORD_PAIR = re.compile(
    rf"\b({_LANG_ALT})\s*(?:->|→|>|-|/|\s+to\s+|\s+into\s+|\s+na\s+)\s*({_LANG_ALT})\b"
)


def _pm_words(f: str) -> int | None:
    m = WORDS_RE.search(f)
    if not m:
        return None
    raw, mult = m.group(1), m.group(2)
    try:
        if re.fullmatch(r"\d{1,3}(?:[ .,]\d{3})+", raw):
            n = Decimal(re.sub(r"[ .,]", "", raw))
        else:
            n = Decimal(raw.replace(",", "."))
    except InvalidOperation:
        return None
    if mult:
        n *= 1000
    return int(n) if n > 0 else None


def _pm_pair(f: str) -> tuple[str | None, str | None]:
    m = LANG_WORD_PAIR.search(f)
    if m:
        return LANGS[m.group(1)], LANGS[m.group(2)]
    return _lang_hint(f)


def _pm_date(f: str, today: date) -> date | None:
    """'by Friday', 'do petka', 'tomorrow', 'in 3 days', 'by 2026-10-20', 'do 20.10.', 'next week'."""
    if m := re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", f):
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    if m := re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})?", f):
        try:
            d = date(int(m.group(3) or today.year), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
        return d if (d >= today or m.group(3)) else date(today.year + 1, d.month, d.day)
    if re.search(r"\btoday\b|\bdanas\b", f):
        return today
    if re.search(r"\btomorrow\b|\bsutra\b", f):
        return today + timedelta(days=1)
    if m := re.search(r"\b(?:in|within|za)\s+(\d{1,3})\s+(?:days?|dana|dan)\b", f):
        return today + timedelta(days=int(m.group(1)))
    if re.search(r"\bnext\s+week\b|\b(?:sledec|iduc)\w*\s+nedelj\w*", f):
        return today + timedelta(days=(4 - today.weekday()) % 7 + 7)
    if re.search(r"\bend\s+of\s+(?:the\s+)?week\b|\bthis\s+week\b|\bkraja?\s+nedelj\w*|\bove\s+nedelj\w*", f):
        return today + timedelta(days=(4 - today.weekday()) % 7)
    for stem, wd in WEEKDAYS.items():
        if re.search(rf"\b(?:by|before|until|on|do|za|pre|u)\s+{stem}\w*", f):
            return today + timedelta(days=(wd - today.weekday()) % 7)
    return None


def parse_pm(text: str, today: date) -> dict[str, Any] | None:
    """The PM question in `text`, or None. Pure: no database access."""
    f = fold(text or "")
    if PM_QUOTE.search(f):
        intent = "draft_quote"
    elif PM_ASSIGN.search(f):
        intent = "propose_assignment"
    elif PM_CAPACITY.search(f):
        intent = "capacity"
    elif PM_RISK.search(f):
        intent = "risk"
    else:
        return None
    src, tgt = _pm_pair(f)
    job = JOB_ID_RE.search(f)
    second = re.search(r"\bsecond\s+review|\bdrug\w*\s+(?:revizij\w*|lektur\w*)", f)
    return {
        "intent": intent,
        "source_lang": src,
        "target_lang": tgt,
        "words": _pm_words(f),
        "by": _pm_date(f, today),
        "job_id": job.group(0) if job else None,
        "step": "second_review" if second else "human_review",
        "tier": _tier_hint(f),
        "folded": f,
    }


def _money_txt(price: dict[str, Any] | None) -> str:
    return f"{price['amount']} {price['currency']}" if price else "no rate on file"


def pm_answer(query: dict[str, Any], locale: str = "en") -> tuple[str, list[dict[str, Any]]]:
    """(reply, plan) for a computed PM query (shape: arbiter.agency.copilot.pm_query)."""
    if query.get("missing"):
        return _localized(" ".join(query["missing"]), locale), []
    intent = query["intent"]
    if intent == "capacity":
        return _localized(_capacity(query), locale), []
    if intent == "risk":
        return _localized(_risk(query), locale), []
    if intent == "propose_assignment":
        reply, plan = _assign(query)
        return _localized(reply, locale), plan
    reply, plan = _quote(query)
    return _localized(reply, locale), plan


def _capacity(query: dict[str, Any]) -> str:
    pair = f"{query['source_lang']}>{query['target_lang']}"
    by = query.get("by")
    rows = query.get("result") or []
    if not rows:
        return f"No active vendor works in {pair}. Add one under Vendors."
    lines = [f"Vendors for {query['words']} words {pair}" + (f" by {by}" if by else "") + ":"]
    for r in rows[:5]:
        verdict = "can make it" if r["can_meet"] else "cannot make it"
        finish = r["earliest_finish"] or "not within the planning horizon"
        lines.append(
            f"- {r['name']}: {verdict} (free {r['free_words']} words, earliest finish {finish}, "
            f"{_money_txt(r.get('price'))})"
        )
    able = [r for r in rows if r["can_meet"]]
    lines.append("")
    lines.append(
        f"{len(able)} of {len(rows)} can deliver in time."
        if by
        else "Give me a date (for example 'by Friday') and I will tell you who makes it."
    )
    return "\n".join(lines)


def _risk(query: dict[str, Any]) -> str:
    rows = query.get("result") or []
    risky = [r for r in rows if r["at_risk"]]
    if not risky:
        if rows:
            return f"No job is at risk right now ({len(rows)} open job(s) with a due date checked)."
        return "No open job has a due date ahead, so nothing is at risk."
    lines = [f"{len(risky)} job(s) at risk of missing the deadline:"]
    for r in risky[:10]:
        who = ", ".join(
            f"{step.replace('_', ' ')}: {v.get('vendor_name') or v['route']}"
            for step, v in r["routes"].items()
        )
        project = f"{r['project']}, " if r.get("project") else ""
        lines.append(
            f"- {r['job_id']} ({project}{r['source_lang']}>{r['target_lang']}): due {r['due_at']}, "
            f"estimated finish {r['estimated_finish']}, {r['remaining_words']} words left ({who}). "
            f"{'; '.join(r['reasons']).capitalize()}."
        )
    lines.append("")
    lines.append("Ask me to propose assignments for one of them to add capacity.")
    return "\n".join(lines)


def _assign(query: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    job = query["job"]
    step = query.get("step", "human_review")
    label = f"{job['job_id']} ({job.get('project') or 'job'}, {job['source_lang']}>{job['target_lang']}, {job['words']} words"
    label += f", due {job['due_at']})" if job.get("due_at") else ")"
    rows = [r for r in query.get("result") or [] if r["eligible"] and r.get("price")]
    if not rows:
        return (
            f"No vendor with a rate for {job['source_lang']}>{job['target_lang']} can take {label}. "
            "Add vendors or rates, or keep the job on the reviewer marketplace.",
            [],
        )
    ranked = sorted(rows, key=lambda r: (not r["can_meet"], r["rank"]))[:3]
    lines = [f"Proposed {step.replace('_', ' ')} for {label}:"]
    for i, r in enumerate(ranked):
        lines.append(
            f"{i + 1}. {r['name']}: {_money_txt(r['price'])}, "
            + ("can make the deadline" if r["can_meet"] else "might not make the deadline")
            + f" (earliest finish {r['earliest_finish'] or 'unknown'})"
        )
    lines.append("")
    lines.append(
        "Apply the plan to send the offer (in this order, first to accept wins). Nothing is sent before that."
    )
    names = ", then ".join(r["name"] for r in ranked)
    action = {
        "type": "create_assignment",
        "summary": f"Offer the {step.replace('_', ' ')} of job {job['job_id']} to {names}",
        "data": {
            "job_id": job["job_id"],
            "step": step,
            "mode": "vendor",
            "vendor_ids": [r["vendor_id"] for r in ranked],
            "strategy": "sequential",
        },
    }
    return "\n".join(lines), [action]


def _quote(query: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    q = query["result"]
    cur = q["currency"]
    langs = ", ".join(q["target_langs"])
    lines = [
        f"Draft quote for {q['account_name']}: {q['words']} words {q['source_lang']}>{langs}, tier {q['tier']}: "
        f"{q['total']} {cur}" + (" (minimum charge applied)." if q.get("minimum_applied") else ".")
    ]
    for b in q["lines"]:
        lines.append(
            f"- {b['target_lang']}: {q['words']} x {b['per_word']} {cur} ({b['rule']}) = {b['amount']} {cur}"
        )
    if not q.get("price_list_id"):
        lines.append("This client has no price list, so the organization's default rates were used.")
    lines.append("")
    lines.append(
        "Applying it records the quote as a deal in stage proposal. Upload the file for a full quote with TM analysis."
    )
    action = {
        "type": "draft_quote",
        "summary": f"Draft quote for {q['account_name']}: {q['total']} {cur} ({q['words']} words, {q['tier']})",
        "data": {
            "account_id": q["account_id"],
            "source_lang": q["source_lang"],
            "target_langs": q["target_langs"],
            "words": q["words"],
            "tier": q["tier"],
        },
    }
    return "\n".join(lines), [action]
