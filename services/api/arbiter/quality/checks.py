"""Deterministic hard QA checks.

Why deterministic checks come first: they are cheap, explainable and never hallucinate.
A blocking issue zeroes the QE score and prevents auto-approval, and NO model output can
override it (the judge is not even called; triage cannot clear it). Non-blocking issues
are shown to reviewers and may be triaged by a model as false positives.

Catalogue (code: severity, blocking):

    empty_target          error    blocking   target has no text but the source does
    untranslated          warning  -          target == source for > 3 words (skipped when every
                                              word is a do-not-translate term)
    tag_missing           error    blocking   standalone code missing (content lost)
    tag_pair_dropped      warning  -          a whole paired code dropped (formatting only, D-009)
    tag_unbalanced        error    blocking   half a pair missing / close without open
    tag_order             error    blocking   broken nesting
    tag_unknown           error    blocking   code not in source
    tag_extra             error    blocking   code duplicated
    tag_malformed         error    blocking   target cannot be parsed
    number_mismatch       error    blocking   numbers differ (locale separators tolerated)
    url_email_mismatch    error    blocking   URL or e-mail address differs
    placeholder_mismatch  error    blocking   {0} %s %1$s {{name}} ${x} {name} differ
    length_exceeded       error    blocking   target plain text longer than max_length
    whitespace_mismatch   info     -          leading/trailing whitespace differs
    double_space          info     -          double space in target, not in source
    repeated_word         warning  -          "the the" in target, not in source
    punctuation_end       warning  -          sentence-final punctuation class differs
    term_missing          error    blocking   mandatory glossary target missing      (R-GL-*)
    term_forbidden        error    blocking   forbidden target used                  (R-GL-*)
    dnt_changed           error    blocking   do-not-translate term altered          (R-GL-*)
    term_preferred_missing warning -          preferred target not used              (R-GL-*)

Numbers: each number token gets the set of values it can mean, so "3,5" (sr, de) equals
"3.5" (en) and "1.000" (de thousands) equals "1,000" (en) and "1000". A token is ambiguous
only when it has a single separator followed by exactly three digits ("1.000" may be one
thousand or 1.0); then both readings are accepted. Ranges ("10-20") are two numbers; signs
are ignored because hyphen vs minus vs en dash usage varies by locale; percentages are
compared by value (the % sign spacing differs by locale: "50%" vs "50 %").
"""

from __future__ import annotations

import re
from collections import Counter
from decimal import Decimal, InvalidOperation

from arbiter.contracts import QaIssue, SegmentContext, TermViolation
from arbiter.engines import tags
from arbiter.fileproc.base import TaggedParseError, validate_tags

CATALOGUE: dict[str, tuple[str, bool]] = {
    "empty_target": ("error", True),
    "untranslated": ("warning", False),
    "tag_missing": ("error", True),
    "tag_pair_dropped": ("warning", False),
    "tag_unbalanced": ("error", True),
    "tag_order": ("error", True),
    "tag_unknown": ("error", True),
    "tag_extra": ("error", True),
    "tag_malformed": ("error", True),
    "number_mismatch": ("error", True),
    "url_email_mismatch": ("error", True),
    "placeholder_mismatch": ("error", True),
    "length_exceeded": ("error", True),
    "whitespace_mismatch": ("info", False),
    "double_space": ("info", False),
    "repeated_word": ("warning", False),
    "punctuation_end": ("warning", False),
    "term_missing": ("error", True),
    "term_forbidden": ("error", True),
    "dnt_changed": ("error", True),
    "term_preferred_missing": ("warning", False),
}
BLOCKING_TERM_CODES = frozenset({"term_missing", "term_forbidden", "dnt_changed"})


def issue(code: str, message: str) -> QaIssue:
    severity, blocking = CATALOGUE[code]
    return QaIssue(code, severity, message, blocking)  # type: ignore[arg-type]


# ------------------------------------------------------------------ patterns

URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"'⟦⟧]+", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PLACEHOLDER_RE = re.compile(
    r"\{\{\s*[\w.]+\s*\}\}"  # {{name}}
    r"|\$\{[^{}]+\}"  # ${x}
    r"|\{\d+\}"  # {0}
    r"|\{[A-Za-z_][\w.]*\}"  # {name}
    r"|%\([A-Za-z_]\w*\)[sdif]"  # %(name)s
    r"|%(?:\d+\$)?[-+0#]*\d*(?:\.\d+)?[sdifuxXeEgGc@]"  # %s %d %1$s %.2f %@
)
NUMBER_RE = re.compile(r"(?<![\w.,])\d{1,3}(?:[    ]\d{3})+(?:[.,]\d+)?(?!\d)|\d+(?:[.,]\d+)*")
_WORD_RE = re.compile(r"\w+", re.U)
_REPEAT_RE = re.compile(r"\b([^\W\d_]+)\s+\1\b", re.I | re.U)
_TRAIL_CLOSERS = "\"')]}»”’›"
_END_CLASS = {
    ".": "stop",
    "。": "stop",
    "．": "stop",
    "…": "stop",
    "!": "excl",
    "！": "excl",
    "¡": "excl",
    "?": "q",
    "？": "q",
    "؟": "q",
    ":": "colon",
    "：": "colon",
    ";": "semi",
    "；": "semi",
}

_TAG_CODE = {
    "missing": "tag_missing",
    "extra": "tag_extra",
    "unbalanced": "tag_unbalanced",
    "order": "tag_order",
    "unknown": "tag_unknown",
    "malformed": "tag_malformed",
}


# ------------------------------------------------------------------ helpers


def number_readings(token: str) -> frozenset[Decimal]:
    """All values a number token can mean across locales."""
    t = re.sub(r"[    ]", "", token)

    def dec(s: str) -> Decimal | None:
        try:
            return Decimal(s).normalize()
        except InvalidOperation:
            return None

    seps = [c for c in t if c in ".,"]
    readings: set[Decimal | None] = set()
    if not seps:
        readings.add(dec(t))
    elif "." in seps and "," in seps:
        last = max(t.rfind("."), t.rfind(","))
        readings.add(dec(re.sub(r"[.,]", "", t[:last]) + "." + t[last + 1 :]))
    elif len(seps) > 1:
        groups = re.split(r"[.,]", t)
        if all(len(g) == 3 for g in groups[1:]):
            readings.add(dec("".join(groups)))  # 1.000.000
        else:
            readings.add(dec("".join(groups[:-1]) + "." + groups[-1]))  # odd: treat last as decimal
    else:
        whole, frac = re.split(r"[.,]", t)
        readings.add(dec(f"{whole}.{frac}"))
        if len(frac) == 3:
            readings.add(dec(whole + frac))  # thousands separator reading
    return frozenset(r for r in readings if r is not None)


def _strip_for_numbers(text: str) -> str:
    for rx in (URL_RE, EMAIL_RE, PLACEHOLDER_RE):
        text = rx.sub(" ", text)
    return text


def extract_numbers(text: str) -> list[frozenset[Decimal]]:
    return [number_readings(m.group(0)) for m in NUMBER_RE.finditer(_strip_for_numbers(text))]


def _match_numbers(src: list[frozenset[Decimal]], tgt: list[frozenset[Decimal]]) -> tuple[list, list]:
    """Maximum bipartite matching (readings must intersect). Returns unmatched (src, tgt)."""
    match_of_tgt: dict[int, int] = {}

    def try_assign(i: int, seen: set[int]) -> bool:
        for j, t in enumerate(tgt):
            if j in seen or not (src[i] & t):
                continue
            seen.add(j)
            if j not in match_of_tgt or try_assign(match_of_tgt[j], seen):
                match_of_tgt[j] = i
                return True
        return False

    matched_src = {i for i in range(len(src)) if try_assign(i, set())}
    return [src[i] for i in range(len(src)) if i not in matched_src], [
        tgt[j] for j in range(len(tgt)) if j not in match_of_tgt
    ]


def _fmt(readings: frozenset[Decimal]) -> str:
    return "/".join(sorted(format(r, "f") for r in readings))


def _trim_url(u: str) -> str:
    return u.rstrip(".,;:!?)»”’\"'")


def word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def _end_class(text: str, lang: str) -> str:
    t = text.rstrip().rstrip(_TRAIL_CLOSERS).rstrip()
    if not t:
        return "none"
    ch = t[-1]
    if ch == ";" and lang.lower().startswith("el"):
        return "q"  # Greek question mark is U+037E or ';'
    if ch == ";":
        return "q"
    return _END_CLASS.get(ch, "none")


def _dnt_only(text: str, ctx: SegmentContext) -> bool:
    dnt = [t.source_term for t in ctx.terms if t.kind == "do_not_translate"]
    if not dnt:
        return False
    rest = text
    for term in sorted(dnt, key=len, reverse=True):
        rest = re.sub(re.escape(term), " ", rest, flags=re.I)
    return word_count(rest) == 0


# ------------------------------------------------------------------ main entry


def run_hard_checks(ctx: SegmentContext, term_violations: list[TermViolation] | None = None) -> list[QaIssue]:
    """Run every deterministic check on one segment. Order of the result is stable."""
    issues: list[QaIssue] = []
    src_plain = tags.plain(ctx.source_tagged)
    tgt_plain = tags.plain(ctx.target_tagged)

    if not tgt_plain.strip() and src_plain.strip():
        issues.append(issue("empty_target", "target is empty"))
        # Everything else would only repeat "it is empty"; tags may still be reported.
        issues.extend(_tag_issues(ctx))
        return issues

    # untranslated
    if (
        word_count(src_plain) > 3
        and " ".join(src_plain.split()).casefold() == " ".join(tgt_plain.split()).casefold()
        and not _dnt_only(src_plain, ctx)
    ):
        issues.append(issue("untranslated", "target is identical to the source"))

    issues.extend(_tag_issues(ctx))

    # numbers
    miss, extra = _match_numbers(extract_numbers(src_plain), extract_numbers(tgt_plain))
    if miss or extra:
        parts = []
        if miss:
            parts.append("missing in target: " + ", ".join(_fmt(r) for r in miss))
        if extra:
            parts.append("not in source: " + ", ".join(_fmt(r) for r in extra))
        issues.append(issue("number_mismatch", "; ".join(parts)))

    # urls and e-mails
    src_links = Counter(_trim_url(u) for u in URL_RE.findall(src_plain)) + Counter(
        EMAIL_RE.findall(src_plain)
    )
    tgt_links = Counter(_trim_url(u) for u in URL_RE.findall(tgt_plain)) + Counter(
        EMAIL_RE.findall(tgt_plain)
    )
    if src_links != tgt_links:
        diff = sorted((src_links - tgt_links).elements()) + sorted((tgt_links - src_links).elements())
        issues.append(issue("url_email_mismatch", "differs: " + ", ".join(diff)))

    # placeholders
    src_ph = Counter(m.replace(" ", "") for m in PLACEHOLDER_RE.findall(src_plain))
    tgt_ph = Counter(m.replace(" ", "") for m in PLACEHOLDER_RE.findall(tgt_plain))
    if src_ph != tgt_ph:
        missing = sorted((src_ph - tgt_ph).elements())
        added = sorted((tgt_ph - src_ph).elements())
        msg = []
        if missing:
            msg.append("missing: " + ", ".join(missing))
        if added:
            msg.append("added: " + ", ".join(added))
        issues.append(issue("placeholder_mismatch", "; ".join(msg)))

    # length
    if ctx.max_length is not None and len(tgt_plain) > ctx.max_length:
        issues.append(issue("length_exceeded", f"{len(tgt_plain)} characters, limit {ctx.max_length}"))

    # whitespace
    lead_s, lead_t = (
        src_plain[: len(src_plain) - len(src_plain.lstrip())],
        tgt_plain[: len(tgt_plain) - len(tgt_plain.lstrip())],
    )
    trail_s, trail_t = src_plain[len(src_plain.rstrip()) :], tgt_plain[len(tgt_plain.rstrip()) :]
    if lead_s != lead_t or trail_s != trail_t:
        issues.append(issue("whitespace_mismatch", "leading or trailing whitespace differs from the source"))
    if "  " in tgt_plain.strip() and "  " not in src_plain.strip():
        issues.append(issue("double_space", "double space in target"))

    # repeated words
    # A target may mirror a reduplication in the source ("bye bye" -> "cao cao"), so only
    # repetitions beyond the number found in the source are reported.
    src_rep = len(_REPEAT_RE.findall(src_plain))
    tgt_rep = [m.group(1) for m in _REPEAT_RE.finditer(tgt_plain)]
    if len(tgt_rep) > src_rep:
        issues.append(issue("repeated_word", "repeated word: " + ", ".join(tgt_rep)))

    # final punctuation
    cs, ct = _end_class(src_plain, ctx.source_lang), _end_class(tgt_plain, ctx.target_lang)
    if cs != ct:
        issues.append(issue("punctuation_end", f"source ends with {cs}, target with {ct}"))

    # glossary
    for v in term_violations or []:
        if v.code in BLOCKING_TERM_CODES:
            issues.append(QaIssue(v.code, "error", v.message, True))
        elif v.code in CATALOGUE:
            issues.append(issue(v.code, v.message))
        else:
            issues.append(QaIssue(v.code, v.severity, v.message, v.severity == "error"))
    return issues


def _tag_issues(ctx: SegmentContext) -> list[QaIssue]:
    try:
        source = tags.to_content(ctx.source_tagged)
    except TaggedParseError as e:
        return [issue("tag_malformed", f"source cannot be parsed: {e}")]
    out = []
    for t in validate_tags(source, ctx.target_tagged):
        if t.severity == "warning":
            out.append(issue("tag_pair_dropped", f"code {t.code_id}: {t.detail}"))
        else:
            out.append(issue(_TAG_CODE.get(t.kind, "tag_malformed"), f"code {t.code_id}: {t.detail}".strip()))
    return out


def blocking(issues: list[QaIssue]) -> list[QaIssue]:
    return [i for i in issues if i.blocking]
