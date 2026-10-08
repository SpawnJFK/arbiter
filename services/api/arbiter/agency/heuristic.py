"""Deterministic rule-based planner: the assistant's brain when the LLM is a mock.

`heuristic_plan(text, context) -> (reply, plan)` reads a plain-language description of an
agency, in English or Serbian (latin, with or without diacritics), and proposes the same
Action list a real model would. It understands:

  agency name     "we are an agency called X", "our agency is called X", "We are X, a ...",
                  "mi smo agencija X", "nasa agencija se zove X", "zovemo se X"
  clients         "our clients are A, B and C", "we work for ...", "klijenti su A, B i C",
                  "radimo za ..."; names must start with a capital letter or a digit
                  (industry guessed from the name: Pharma -> pharma, Soft -> software, ...)
  workflow        steps in the order mentioned: TM, MT (DeepL/Google as engine), best-of-N,
                  QE/QA, senate, AI review, review/revizija/lektura/post-editing, second
                  review/druga revizija/lektura after revizija, client approval/odobrenje
                  klijenta, delivery/isporuka; DTP/prelom is ignored with a note.
                  "druga revizija za farmaciju" scopes the second review to that domain: two
                  workflows, and accounts of that industry get the stricter one.
                  Tier: human review -> full (hybrid when only low scores go to a human),
                  AI review -> ai_review, none -> auto; R-SEG-12: regulated -> never auto/ai_review.
  rates           "0.08 EUR po reci", "8 cents per word", "EUR 0,10/word", "minimum 20 EUR",
                  tier and target language hints in the same clause
  dashboard       revenue/prihod, margin/marza, overdue/kasni, deals/prodaja, active jobs,
                  quality, words, clients, reviewer cost, activities, deliveries
  questions       "koliko poslova kasni?", "how much revenue ...", answered from the context
                  summary only, with an empty plan

Output is English (the product is English-first): replies, workflow/price list/dashboard
names and summaries. User-given proper names (agency, clients) are kept verbatim. For a
locale other than English the reply carries a note that only the AI model localizes replies.
It never invents names or e-mails: only what the text contains becomes an account. When
essential information is missing it still proposes what it can and asks in the reply.
Cross-references between actions use "@<index>" (resolved when the plan is applied).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

# ----------------------------------------------------------------------------- text helpers

_FOLD = str.maketrans("šđčćžŠĐČĆŽ", "sdcczSDCCZ")
_ABBREV = frozenset(
    {
        "inc",
        "ltd",
        "llc",
        "co",
        "corp",
        "gmbh",
        "doo",
        "ad",
        "sa",
        "srl",
        "bv",
        "plc",
        "mr",
        "dr",
        "npr",
        "tj",
        "itd",
        "st",
        "vs",
    }
)


def fold(text: str) -> str:
    """Lowercase, diacritics to ASCII, SAME LENGTH as the input (positions stay valid)."""
    out = []
    for ch in text.translate(_FOLD):
        low = ch.lower()
        out.append(low if len(low) == 1 else ch)
    return "".join(out)


def sentences(text: str) -> list[tuple[int, int]]:
    """Sentence spans. A period after a one-letter token (d.o.o.) or a company abbreviation
    (Ltd., Inc.) does not end a sentence; neither does a decimal point."""
    spans: list[tuple[int, int]] = []
    start = 0
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        end_here = False
        if ch in "!?;\n":
            end_here = True
        elif ch == "." and (i + 1 == n or text[i + 1].isspace()):
            j = i - 1
            while j >= 0 and text[j].isalnum():
                j -= 1
            token, prev = text[j + 1 : i], (text[j] if j >= 0 else "")
            end_here = not ((len(token) == 1 and prev == ".") or token.lower() in _ABBREV)
        if end_here:
            if text[start:i].strip():
                spans.append((start, i))
            start = i + 1
        i += 1
    if text[start:].strip():
        spans.append((start, n))
    return spans


def _strip_period(name: str) -> str:
    """Drop a sentence period, keep the one of "d.o.o." or "Ltd."."""
    if not name.endswith("."):
        return name
    token = re.split(r"[\s.]", name[:-1])[-1]
    if len(token) == 1 or token.lower() in _ABBREV:
        return name
    return name[:-1].rstrip()


def _clean_name(raw: str) -> str | None:
    name = raw.strip().strip("\"'“”„‘’«»").strip()
    cut = re.search(
        r"(?:,|;|\(|\s[-–]\s|:|\s+(?:i|and|a|koja|koji|which|that|who|iz|from|based|sa sedistem|"
        r"with|sa|we|mi|nasa|our|u)\s)",
        fold(name),
    )
    if cut:
        name = name[: cut.start()]
    name = _strip_period(name.strip()).strip("\"'“”„«»").strip()
    words = name.split()
    if not words or len(words) > 6 or len(name) > 120:
        return None
    if not (name[0].isupper() or name[0].isdigit()):
        return None
    return name


# ----------------------------------------------------------------------------- vocabularies

LANGS = {
    "engleski": "en", "engleskog": "en", "english": "en",
    "srpski": "sr", "srpskog": "sr", "serbian": "sr",
    "nemacki": "de", "nemackog": "de", "german": "de",
    "francuski": "fr", "francuskog": "fr", "french": "fr",
    "italijanski": "it", "italijanskog": "it", "italian": "it",
    "spanski": "es", "spanskog": "es", "spanish": "es",
    "ruski": "ru", "ruskog": "ru", "russian": "ru",
    "hrvatski": "hr", "hrvatskog": "hr", "croatian": "hr",
    "slovenacki": "sl", "slovenian": "sl",
    "madjarski": "hu", "madarski": "hu", "hungarian": "hu",
    "rumunski": "ro", "romanian": "ro",
    "bugarski": "bg", "bulgarian": "bg",
    "makedonski": "mk", "macedonian": "mk",
    "grcki": "el", "greek": "el",
    "turski": "tr", "turkish": "tr",
    "kineski": "zh", "chinese": "zh",
    "japanski": "ja", "japanese": "ja",
    "polski": "pl", "poljski": "pl", "polish": "pl",
    "ceski": "cs", "czech": "cs",
}  # fmt: skip
LANG_CODES = frozenset(LANGS.values()) | {
    "pt",
    "nl",
    "sv",
    "da",
    "fi",
    "no",
    "uk",
    "ar",
    "ko",
    "sk",
    "bs",
    "sq",
}

INDUSTRIES: list[tuple[str, str]] = [
    ("pharma", r"pharm|farma|farmac|\blek\w*|drug|biotech"),
    ("medical", r"medic|medtech|zdrav|health|bolnic|klinik|clinic|hospital"),
    ("legal", r"\blaw\b|legal|pravn|advokat|attorney"),
    ("finance", r"\bbank|banka|financ|finans|osiguranj|insur|capital"),
    ("software", r"soft|tech|tehno|\bit\b|\bapp|digital|cloud|data|cyber|\bai\b"),
    ("automotive", r"\bauto|motor|vozil"),
    ("marketing", r"marketing|media|mediji|reklam|advert"),
]
DOMAIN_LABEL = {
    "pharma": "pharma",
    "medical": "medical",
    "legal": "legal",
    "finance": "finance",
    "software": "software",
    "automotive": "automotive",
    "marketing": "marketing",
}

# (kind, pattern) in priority order: longer phrases are matched and masked first.
STEP_PATTERNS: list[tuple[str, str]] = [
    (
        "client_review",
        r"\b(?:odobrenj\w*|odobravanj\w*|potvrd\w*|saglasnost\w*)\s+(?:od\s+(?:strane\s+)?)?(?:klijent\w*|narucioc\w*)"
        r"|\b(?:klijent\w*|narucioc\w*)\s+(?:odobrava|odobri|potvrdjuje|potvrduje|potvrdi|pregleda|daje\s+odobrenje)"
        r"|\b(?:client|customer)(?:'s)?\s+(?:approval|review|sign[- ]?off|check|acceptance)"
        r"|\bapproved\s+by\s+the\s+(?:client|customer)|\bsign[- ]?off\b",
    ),
    (
        "second_review",
        r"\b(?:drug\w*|dupl\w*|dvostruk\w*)\s+(?:revizij\w*|lektur\w*|prover\w*|kontrol\w*|pregled\w*)"
        r"|\bdva\s+revizor\w*|\bdvojic\w*\s+revizor\w*"
        r"|\bsecond\s+(?:review\w*|revision|proofread\w*|check|pass|linguist)|\btwo\s+reviewers|\bdouble\s+(?:review|check)"
        r"|\bfour[- ]eyes|\b4[- ]eyes",
    ),
    ("dtp", r"\bdtp\b|\bprelom\w*|\bdesktop\s+publishing|\bformatiranj\w*|\blayout\b|\bprepress\b"),
    (
        "ai_review",
        r"\bai\s+(?:review\w*|revizij\w*|prover\w*|editor\w*|edit\w*|lektur\w*|korekcij\w*|post[- ]?edit\w*)"
        r"|\bautomatsk\w*\s+(?:revizij\w*|korekcij\w*|lektur\w*)|\bautomatic\s+(?:review|post[- ]?edit\w*)",
    ),
    ("senate", r"\bsenat\w*|\bsenate\b|\bpanel\s+(?:of\s+)?(?:models|ai)"),
    (
        "translation_senate",
        r"\bbest[- ]of[- ]?n\b|\bvise\s+(?:masin\w*|engine\w*|mt\b|alata)|\bmultiple\s+(?:engines|mt\b)|\bnajbolj\w+\s+od\s+vise",
    ),
    (
        "qe",
        r"\bqe\b|\bquality\s+estimation|\b(?:procen\w*|ocen\w*|prover\w*|kontrol\w*)\s+kvalitet\w*|\bqa\b"
        r"|\bquality\s+(?:check|score|scoring|assurance)|\bscor(?:e|ing)\b",
    ),
    (
        "mt",
        r"\bmt\b|\bmachine\s+translat\w*|\bmasinsk\w*\s+prevo\w*|\bautomatsk\w*\s+prevo\w*|\bdeepl\b|\bgoogle\s+translate"
        r"|\bai\s+prevo\w*|\bai\s+translat\w*|\bneural\b|\bnmt\b",
    ),
    ("tm", r"\btm\b|\btranslation\s+memor\w*|\bprevodilack\w*\s+memorij\w*|\bmemorij\w*\s+prevo\w*"),
    (
        "human_translation",
        r"\bljudsk\w*\s+prevo\w*|\bhuman\s+translat\w*|\bprevod\w*\s+(?:rade|radi)\s+prevodioc\w*|\btranslated\s+by\s+(?:our\s+)?translators",
    ),
    (
        "human_review",
        r"\brevizij\w*|\brevidir\w*|\blektur\w*|\bproofread\w*|\breview\w*|\brevision\w*|\bpost[- ]?edit\w*|\bmtpe\b"
        r"|\bediting\b|\bredaktur\w*|\bkorektur\w*|\bljudsk\w*\s+prover\w*|\bhuman\s+(?:check|review\w*)",
    ),
    ("delivery", r"\bisporu\w*|\bdeliver\w*|\bpredaj\w*\s+klijent\w*"),
]
CANONICAL = ["tm", "mt", "translation_senate", "qe", "senate", "ai_review", "human_review", "second_review", "client_review", "delivery"]  # fmt: skip
WORKFLOW_TRIGGER = re.compile(
    r"\bworkflow\w*|\bpipeline\b|\btok\w*\s+rada|\bradn\w*\s+tok\w*|\bproces\w*|\bprocedur\w*|\bpostupak|\bkorac\w*|\bsteps?\b"
    r"|\bprvo\b|\bfirst\b|\bzatim\b|\bthen\b|\bpa\s|\bnakon\b|\bafter\b|\bposle\b"
)
LOW_SCORE_ONLY = re.compile(
    r"\b(?:samo|only|just)\b[^.]{0,60}\b(?:nizak|nisk\w*|low\w*|ispod|below|los\w*|bad|sumnjiv\w*|problem\w*)"
    r"|\bispod\s+praga|\bbelow\s+(?:the\s+)?threshold|\blow[- ]scor\w*|\bhybrid\b|\bhibrid\w*"
)
DASHBOARD_TRIGGER = re.compile(
    r"\bdashboard\w*|\bkontroln\w*\s+tabl\w*|\bpregled\w*|\bizvestaj\w*|\bizvjestaj\w*|\breport\w*|\bkpi\w*"
    r"|\bstatistik\w*|\b(?:hocu|zelim|zelimo|hocemo|voleo bih|volela bih)\s+da\s+(?:vidim|vidimo|pratim|pratimo)"
    r"|\bwant\s+to\s+(?:see|track)|\bi'?d\s+like\s+to\s+see|\btrack\b|\bpracenj\w*|\bpratim\w*|\bpratiti\b|\bmetric\w*|\bmetrik\w*"
)
METRIC_PATTERNS: list[tuple[str, list[tuple[str, str]]]] = [
    (r"\bprihod\w*|\bzarad\w*|\brevenue\w*|\bincome\b|\bturnover\b|\bpromet\w*|\bsales\s+volume", [("kpi", "revenue"), ("line", "revenue_by_month")]),
    (r"\bmarz\w*|\bmargin\w*|\bprofit\w*|\bdobit\w*", [("kpi", "margin"), ("kpi", "margin_pct")]),
    (r"\bkasn\w*|\bkasnj\w*|\boverdue\b|\blate\b|\bdeadline\w*|\brokov\w*|\bzakasn\w*|\bprobi\w*\s+rok", [("kpi", "jobs_overdue"), ("table", "overdue_jobs")]),
    (r"\bdeal\w*|\bprodaj\w*|\bpipeline\b|\bponud\w*|\bleads?\b|\bsales\b|\bprilik\w*", [("pipeline", "deals_by_stage"), ("kpi", "open_deals_value")]),
    (r"\baktivn\w*\s+posl\w*|\bposl\w*\s+u\s+toku|\bactive\s+jobs|\bin\s+progress|\bjobs?\s+by\s+state|\bstanj\w*\s+posl\w*", [("kpi", "jobs_active"), ("bar", "jobs_by_state")]),
    (r"\bkvalitet\w*|\bquality\b|\bauto[- ]?(?:rate|approv\w*)|\bautomatsk\w*\s+odobr\w*|\bgresk\w*|\berrors?\b", [("kpi", "auto_rate"), ("kpi", "escaped_rate"), ("line", "auto_rate_by_month")]),
    (r"\breci\b|\bwords?\b|\bobim\w*|\bvolume\b|\bjezick\w*\s+par\w*|\blanguage\s+pairs?", [("kpi", "words_delivered"), ("bar", "words_by_pair")]),
    (r"\bklijent\w*|\bclients?\b|\baccounts?\b|\bcustomers?\b|\bkupc\w*|\bkupac\w*", [("bar", "revenue_by_account"), ("table", "top_accounts")]),
    (r"\btrosk\w*\s+(?:revizor\w*|lektor\w*)|\breviewer\s+cost\w*|\bcost\s+of\s+review\w*|\btrosk\w*", [("kpi", "reviewer_cost")]),
    (r"\baktivnost\w*|\bactivit\w*|\bzadac\w*|\bzadatk\w*|\btasks?\b|\bfollow[- ]?ups?\b|\bpoziv\w*", [("table", "open_activities")]),
    (r"\bisporu\w*|\bdeliver\w*", [("table", "recent_deliveries"), ("kpi", "words_delivered")]),
]  # fmt: skip
DEFAULT_DASHBOARD: list[tuple[str, str]] = [
    ("kpi", "revenue"),
    ("kpi", "margin_pct"),
    ("kpi", "jobs_active"),
    ("kpi", "jobs_overdue"),
    ("line", "revenue_by_month"),
    ("pipeline", "deals_by_stage"),
    ("table", "overdue_jobs"),
]
TYPE_ORDER = {"kpi": 0, "pipeline": 1, "line": 2, "bar": 3, "table": 4}


@dataclass
class _Found:
    agency: str | None = None
    agency_kind: bool = False
    regulated: bool = False
    clients: list[tuple[str, str | None]] = field(default_factory=list)  # (name, industry)
    steps: list[tuple[int, str, dict[str, Any]]] = field(default_factory=list)  # (pos, kind, params)
    second_domain: str | None = None
    human_translation: bool = False
    dtp: bool = False
    low_score_only: bool = False
    qe_threshold: float | None = None
    rates: list[dict[str, Any]] = field(default_factory=list)
    currency: str | None = None
    minimum: Decimal | None = None
    metrics: list[tuple[str, str]] = field(default_factory=list)
    wants_dashboard: bool = False
    team: bool = False
    contacts_hint: bool = False
    langs_mentioned: bool = False
    notes: list[str] = field(default_factory=list)


# ----------------------------------------------------------------------------- extraction


AGENCY_PATTERNS = [
    r"\b(?:we\s+are|we're|this\s+is)\s+(?:an?\s+)?(?:[a-z-]+\s+){0,3}?(?:agency|company|firm|team|studio|lsp|business)\s+(?:called|named)\s+(?P<n>.+)",
    r"\b(?:our|my|the)\s+(?:[a-z-]+\s+){0,2}?(?:agency|company|firm|team|studio|business)(?:'s\s+name)?\s+is\s+(?:called\s+|named\s+)?(?P<n>.+)",
    r"\b(?:agency|company|firm)\s+(?:called|named)\s+(?P<n>.+)",
    r"\bmi\s+smo\s+(?:jedna\s+)?(?:mala\s+|velika\s+|nova\s+)?(?:prevodilack\w*\s+)?(?:agencij\w*|firm\w*|kompanij\w*)\s+(?:za\s+prevod\w*\s+)?(?P<n>.+)",
    r"\b(?:nasa|moja)\s+(?:prevodilack\w*\s+)?(?:agencij\w*|firm\w*|kompanij\w*)\s+se\s+zove\s+(?P<n>.+)",
    r"\b(?:agencij\w*|firm\w*)\s+(?:se\s+zove|pod\s+imenom|po\s+imenu)\s+(?P<n>.+)",
    r"\bzovemo\s+se\s+(?P<n>.+)",
    r"\bime\s+(?:nase\s+)?(?:agencije|firme)\s+je\s+(?P<n>.+)",
]
AGENCY_CASED = [
    # "We are Northwind Language Services." : a whole sentence that is just a capitalised name.
    r"^\s*(?:We\s+are|We're|Mi\s+smo)\s+(?P<n>[A-Z0-9][\w&'.-]*(?:\s+[A-Z0-9][\w&'.-]*){0,5})\s*[.!]?\s*$",
    r"\b(?:[Ww]e\s+are|[Ww]e're|[Mm]i\s+smo)\s+(?P<n>[A-Z0-9][\w&'.-]*(?:\s+[A-Z0-9][\w&'.-]*){0,4})\s*,\s*(?:an?\s+|jedna\s+)?\w*\s*(?:translation|localization|prevodilack|prevodilačk|agency|agencija)",
]
CLIENT_PATTERNS = [
    r"\b(?:our\s+|main\s+|key\s+)*(?:clients|customers)\s+(?:are|include|:)\s*:?\s*(?P<l>.+)",
    r"\bwe\s+(?:work|translate)\s+for\s+(?P<l>.+)",
    r"\bwe\s+have\s+(?:\w+\s+)?(?:clients|customers)\s*(?::|-|like|such\s+as|including)\s*(?P<l>.+)",
    r"\b(?:nasi\s+|glavni\s+|kljucni\s+|stalni\s+)*(?:klijenti|kupci|narucioci)\s+(?:su|nam\s+su)\s*:?\s*(?P<l>.+)",
    r"\b(?:klijenti|clients)\s*:\s*(?P<l>.+)",
    r"\bradimo\s+za\s+(?P<l>.+)",
    r"\bimamo\s+(?:\w+\s+)?klijent\w*\s*(?::|-|kao\s+sto\s+su|npr\.?)\s*(?P<l>.+)",
]
GENERIC_CLIENT = re.compile(r"^(?:itd|etc|others?|drugi\w*|ostali\w*|and more|i drugi|many more|razni\w*)$")


def _agency(text: str, f: str, found: _Found) -> None:
    for a, b in sentences(text):
        seg, fseg = text[a:b], f[a:b]
        if re.search(
            r"\bagencij\w*|\bagency\b|\blsp\b|\bprevodilack\w*|\btranslation\s+(?:company|firm|studio)", fseg
        ):
            found.agency_kind = True
        if found.agency:
            continue
        for pat in AGENCY_PATTERNS:
            m = re.search(pat, fseg)
            if m:
                name = _clean_name(seg[m.start("n") :])
                if name:
                    found.agency = name
                    break
        if not found.agency:
            for pat in AGENCY_CASED:
                m = re.search(pat, seg.translate(_FOLD))
                if m:
                    found.agency = _clean_name(m.group("n"))
                    break
    if re.search(
        r"\bregulated\b|\bregulisan\w*|\bmedical\s+devices?\b|\bmedicinsk\w+\s+(?:uredjaj\w*|sredstv\w*)", f
    ):
        found.regulated = True


def _industry(name: str) -> str | None:
    fn = fold(name)
    for ind, pat in INDUSTRIES:
        if re.search(pat, fn):
            return ind
    return None


def _clients(text: str, f: str, found: _Found) -> None:
    seen: set[str] = set()
    for a, b in sentences(text):
        seg, fseg = text[a:b], f[a:b]
        for pat in CLIENT_PATTERNS:
            m = re.search(pat, fseg)
            if not m:
                continue
            rest, frest = seg[m.start("l") :], fseg[m.start("l") :]
            # split on commas, semicolons and the words and / i / te / kao i (positions from the folded copy)
            parts: list[str] = []
            last = 0
            for sep in re.finditer(
                r"\s*[,;]\s*(?:(?:and|i|te)\s+)?|\s+(?:and|i|te|kao\s+i|as\s+well\s+as)\s+", frest
            ):
                parts.append(rest[last : sep.start()])
                last = sep.end()
            parts.append(rest[last:])
            for raw in parts:
                hint = " ".join(re.findall(r"\(([^)]*)\)", raw))
                raw = re.sub(r"\([^)]*\)", " ", raw)
                name = _clean_name(raw)
                if not name or GENERIC_CLIENT.match(fold(name)) or fold(name) in seen:
                    continue
                seen.add(fold(name))
                found.clients.append((name, _industry(f"{name} {hint}")))
            break
    if re.search(r"@|\bkontakt\w*|\bcontact\w*|\bemail\w*|\be-mail\w*", f):
        found.contacts_hint = True


def _steps(text: str, f: str, found: _Found) -> None:
    spans = sentences(text)
    picked = []
    for a, b in spans:
        fseg = f[a:b]
        hits = sum(1 for _, pat in STEP_PATTERNS if re.search(pat, fseg))
        if WORKFLOW_TRIGGER.search(fseg) and hits or hits >= 2:
            picked.append((a, b))
    if not picked:
        return
    masked = list(f)
    first_human: str | None = None
    for a, b in picked:
        for kind, pat in STEP_PATTERNS:
            for m in re.finditer(pat, "".join(masked[a:b])):
                s, e = a + m.start(), a + m.end()
                word = f[s:e]
                for k in range(s, e):
                    masked[k] = " "
                params: dict[str, Any] = {}
                if kind == "dtp":
                    found.dtp = True
                    continue
                if kind == "human_translation":
                    found.human_translation = True
                    continue
                if kind == "mt":
                    if "deepl" in word:
                        params["engine"] = "deepl"
                    elif "google" in word:
                        params["engine"] = "google"
                if kind == "second_review":
                    tail = f[e : min(b, e + 50)]
                    dm = re.match(
                        r"\s*(?:,\s*)?(?:samo\s+|only\s+)?(?:za|for|kod|on)\s+(?:the\s+)?(?P<d>[a-z]+)", tail
                    )
                    if dm:
                        found.second_domain = _industry(dm.group("d")) or found.second_domain
                if kind == "human_review":
                    stem = "lektur" if re.match(r"lektur|proofread|korektur", word) else "rev"
                    if first_human is None:
                        first_human = stem
                    elif stem != first_human:
                        kind = "second_review"  # revizija ... lektura: two different human passes
                    else:
                        continue
                found.steps.append((s, kind, params))
        if LOW_SCORE_ONLY.search(f[a:b]):
            found.low_score_only = True
        tm_ = re.search(r"(?:prag\w*|threshold|score|ocen\w*)\D{0,15}(\d{2}(?:[.,]\d)?)", f[a:b])
        if tm_:
            val = float(tm_.group(1).replace(",", "."))
            if 50 <= val <= 99:
                found.qe_threshold = val


_CUR = r"€|eur\w*|evr\w*|usd|\$|dolar\w*|dollar\w*|rsd|din\w*|gbp|£|chf"
RATE_RE = re.compile(
    rf"(?P<cur1>{_CUR})?\s*(?P<num>\d+(?:[.,]\d+)?)\s*(?P<cur2>{_CUR}|cents?|cent[ia]?|euro\s*cents?)?\s*"
    r"(?:po|per|/|za|a|for\s+each|for\s+a|each)\s*(?:jednoj\s+|one\s+|a\s+|each\s+)?(?:recima|reci|rec|rijeci|words?|wrd)\b"
)
MIN_RE = re.compile(
    rf"\b(?:minimum|minimaln\w*\s+(?:cen\w*|naplat\w*|naknad\w*|porudzbin\w*|iznos\w*)|min\.?)\s*(?:charge|fee|order|of|je|od|:)?\s*:?\s*"
    rf"(?P<cur1>{_CUR})?\s*(?P<num>\d+(?:[.,]\d+)?)\s*(?P<cur2>{_CUR})?"
)


def _currency(token: str | None) -> str | None:
    if not token:
        return None
    t = token.strip()
    if t in ("€",) or t.startswith(("eur", "evr")):
        return "EUR"
    if t == "$" or t.startswith(("usd", "dolar", "dollar")):
        return "USD"
    if t.startswith(("rsd", "din")):
        return "RSD"
    if t in ("gbp", "£"):
        return "GBP"
    if t == "chf":
        return "CHF"
    return None


def _lang_hint(clause: str) -> tuple[str | None, str | None]:
    src = tgt = None
    m = re.search(r"\b([a-z]{2})\s*(?:-|>|→|->|/|to)\s*([a-z]{2})\b", clause)
    if m and m.group(1) in LANG_CODES and m.group(2) in LANG_CODES:
        return m.group(1), m.group(2)
    for word, code in LANGS.items():
        if re.search(rf"\b(?:sa|from|iz)\s+{word}\b", clause):
            src = code
        if re.search(rf"\b(?:na|into|to|za|for)\s+{word}\b", clause):
            tgt = code
    return src, tgt


def _tier_hint(clause: str) -> str | None:
    if re.search(r"\bhibrid\w*|\bhybrid\b", clause):
        return "hybrid"
    if re.search(r"\bai\s+(?:review|revizij\w*|prover\w*)", clause):
        return "ai_review"
    if re.search(r"\bmt\b|\bmachine\b|\bmasinsk\w*|\bsamo\s+prevod|\bauto\b|\braw\b", clause):
        return "auto"
    if re.search(r"\brevizij\w*|\breview\w*|\bhuman\b|\bljudsk\w*|\bfull\b|\bpun\w*|\blektur\w*", clause):
        return "full"
    return None


def _rates(f: str, found: _Found) -> None:
    for m in RATE_RE.finditer(f):
        cur_tok = m.group("cur1") or m.group("cur2")
        cents = bool(m.group("cur2") and re.match(r"cent|euro\s*cent", m.group("cur2")))
        if not cur_tok and not cents:
            continue
        try:
            value = Decimal(m.group("num").replace(",", "."))
        except InvalidOperation:
            continue
        cur = _currency(cur_tok) if not cents else None
        if cents:
            value = value / 100
            around = f[max(0, m.start() - 40) : m.end() + 10]
            cur = "USD" if re.search(r"\$|usd|dolar|dollar", around) else "EUR"
        if value <= 0 or value > 100:
            continue
        a = max(
            f.rfind(",", 0, m.start()),
            f.rfind(".", 0, m.start() - 1) if m.start() else -1,
            f.rfind(";", 0, m.start()),
        )
        ends = [x for x in (f.find(",", m.end()), f.find(";", m.end()), f.find(". ", m.end())) if x != -1]
        clause = f[a + 1 : min(ends) if ends else len(f)]
        src, tgt = _lang_hint(clause)
        found.rates.append(
            {
                "source_lang": src,
                "target_lang": tgt,
                "tier": _tier_hint(clause),
                "per_word": value.normalize(),
            }
        )
        found.currency = found.currency or cur
        if src or tgt:
            found.langs_mentioned = True
    mm = MIN_RE.search(f)
    if mm:
        try:
            found.minimum = Decimal(mm.group("num").replace(",", "."))
        except InvalidOperation:
            found.minimum = None
        found.currency = found.currency or _currency(mm.group("cur1") or mm.group("cur2"))
    if any(re.search(rf"\b{w}\b", f) for w in LANGS):
        found.langs_mentioned = True


def _dashboard(text: str, f: str, found: _Found) -> None:
    for a, b in sentences(text):
        fseg = f[a:b]
        if not DASHBOARD_TRIGGER.search(fseg):
            continue
        found.wants_dashboard = True
        hits: list[tuple[int, list[tuple[str, str]]]] = []
        for pat, widgets in METRIC_PATTERNS:
            m = re.search(pat, fseg)
            if m:
                hits.append((m.start(), widgets))
        for _, widgets in sorted(hits, key=lambda h: h[0]):
            for w in widgets:
                if w not in found.metrics:
                    found.metrics.append(w)
    if not found.wants_dashboard and re.search(r"\bcrm\b|\bdashboard\w*|\bkontroln\w*\s+tabl\w*", f):
        found.wants_dashboard = True


def _team(f: str, found: _Found) -> None:
    if re.search(
        r"\b(?:\d+|dva|dve|tri|cetiri|pet|sest|sedam|osam|devet|deset|two|three|four|five|six|seven|eight|nine|ten)\s+"
        r"(?:revizor\w*|prevodila\w*|prevodioc\w*|lektor\w*|reviewers?|translators?|proofreaders?|linguists?|people|ljudi|zaposlen\w*|pm\w*|project\s+managers?)",
        f,
    ) or re.search(r"\b(?:nas\s+tim|our\s+team|tim\s+(?:od|cine)|team\s+of)\b", f):
        found.team = True


# ----------------------------------------------------------------------------- plan building


def _workflow_steps(
    found: _Found, regulated: bool, notes: list[str]
) -> tuple[list[str], dict[str, dict[str, Any]], str]:
    kinds: list[str] = []
    params: dict[str, dict[str, Any]] = {}
    for _, kind, p in sorted(found.steps, key=lambda x: x[0]):
        if kind not in kinds:
            kinds.append(kind)
            params[kind] = p
    if not kinds and not found.human_translation:
        return [], {}, ""
    if "tm" not in kinds:
        kinds.insert(0, "tm")
        notes.append("I added TM (translation memory) as the first step; it always helps.")
    if not any(k in kinds for k in ("mt", "translation_senate")):
        if found.human_translation:
            if "human_review" not in kinds:
                kinds.append("human_review")
        else:
            kinds.insert(1, "mt")
            notes.append("You did not mention machine translation; I added MT after TM.")
    reviews = [
        k for k in kinds if k in ("senate", "ai_review", "human_review", "second_review", "client_review")
    ]
    if reviews and "qe" not in kinds:
        kinds.append("qe")
        notes.append("I added QE (quality estimation) before review; it decides what goes to a human.")
    if "second_review" in kinds and "human_review" not in kinds:
        kinds.append("human_review")
    humans = "human_review" in kinds
    if humans:
        tier = "hybrid" if found.low_score_only and "second_review" not in kinds else "full"
    elif "ai_review" in kinds:
        tier = "ai_review"
    else:
        tier = "auto"
    if regulated and tier in ("auto", "ai_review"):
        kinds = [k for k in kinds if k != "ai_review"]
        kinds.append("human_review")
        tier = "full"
        notes.append(
            "Regulated vertical: every segment needs a human reviewer (R-SEG-12), so I added human review."
        )
    if tier == "hybrid" and "senate" not in kinds:
        kinds.append("senate")
    if "delivery" not in kinds:
        kinds.append("delivery")
    kinds = sorted(dict.fromkeys(kinds), key=CANONICAL.index)
    if found.qe_threshold is not None:
        params["qe"] = {"threshold": found.qe_threshold}
    return kinds, params, tier


def _step_list(kinds: list[str], params: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"kind": k, "params": dict(params.get(k) or {})} for k in kinds]


STEP_LABEL = {
    "tm": "TM",
    "mt": "MT",
    "translation_senate": "best-of-N translation",
    "qe": "QE",
    "senate": "senate",
    "ai_review": "AI review",
    "human_review": "review",
    "second_review": "second review",
    "client_review": "client approval",
    "delivery": "delivery",
}


def _steps_text(kinds: list[str]) -> str:
    return " > ".join(STEP_LABEL[k] for k in kinds)


def heuristic_plan(
    text: str, context: dict[str, Any] | None = None, locale: str = "en"
) -> tuple[str, list[dict[str, Any]]]:
    """(reply, plan) for one user message. Deterministic; see the module docstring.

    Output (reply, names, summaries) is always English: the product is English-first. For any
    other locale the reply says that only the AI model localizes replies.
    """
    context = context or {}
    text = text or ""
    f = fold(text)
    org = context.get("org") or {}
    found = _Found()
    _agency(text, f, found)
    _clients(text, f, found)
    _steps(text, f, found)
    _rates(f, found)
    _dashboard(text, f, found)
    _team(f, found)
    regulated = bool(org.get("regulated")) or found.regulated
    notes: list[str] = []
    questions: list[str] = []
    plan: list[dict[str, Any]] = []

    # 1. organization
    org_data: dict[str, Any] = {}
    if found.agency and found.agency != org.get("name"):
        org_data["name"] = found.agency
    if found.agency_kind and org.get("vertical") != "translation_agency":
        org_data["vertical"] = "translation_agency"
    if found.regulated and not org.get("regulated"):
        org_data["regulated"] = True
    if org_data:
        bits = []
        if "name" in org_data:
            bits.append(f'name "{org_data["name"]}"')
        if "vertical" in org_data:
            bits.append("vertical: translation agency")
        if "regulated" in org_data:
            bits.append("regulated vertical (R-SEG-12)")
        plan.append(
            {
                "type": "update_org",
                "summary": "Organization settings: " + ", ".join(bits),
                "data": org_data,
            }
        )

    # 2. workflows
    kinds, params, tier = _workflow_steps(found, regulated, notes)
    main_ref = domain_ref = None
    domain = found.second_domain if "second_review" in kinds else None
    if kinds:
        main_kinds = [k for k in kinds if k != "second_review"] if domain else kinds
        main_tier = tier
        if domain and main_tier == "full" and "human_review" not in main_kinds:
            main_kinds.append("human_review")
        name = "Standard workflow"
        plan.append(
            {
                "type": "create_workflow",
                "summary": f'Workflow "{name}": ' + _steps_text(main_kinds) + f" ({main_tier})",
                "data": {
                    "name": name,
                    "description": "Created from the agency description.",
                    "tier": main_tier,
                    "steps": _step_list(main_kinds, params),
                    "is_default": True,
                },
            }
        )
        main_ref = len(plan) - 1
        if domain:
            label = DOMAIN_LABEL.get(domain, domain)
            dname = f"{label.capitalize()} workflow"
            dtier = "full"
            plan.append(
                {
                    "type": "create_workflow",
                    "summary": f'Workflow "{dname}": ' + _steps_text(kinds) + f" ({dtier})",
                    "data": {
                        "name": dname,
                        "description": f"Second review only for {label} clients.",
                        "content_type": domain,
                        "tier": dtier,
                        "steps": _step_list(kinds, params),
                    },
                }
            )
            domain_ref = len(plan) - 1
    else:
        questions.append(
            "What does your workflow look like (for example: MT, QE, review, second review, client approval)?"
        )
    if found.dtp:
        notes.append(
            "DTP/layout is not an Arbiter pipeline step; I left it out (it stays a manual step after delivery)."
        )

    # 3. price list
    pl_ref = None
    if found.rates:
        tiers_used = [tier or "full"]
        if domain_ref is not None and "full" not in tiers_used:
            tiers_used.append("full")
        rates: list[dict[str, Any]] = []
        seen: set[tuple[Any, Any, str]] = set()
        for r in found.rates:
            for tr in [r["tier"]] if r["tier"] else tiers_used:
                key = (r["source_lang"], r["target_lang"], tr)
                if key in seen:
                    continue
                seen.add(key)
                rates.append(
                    {
                        "source_lang": r["source_lang"],
                        "target_lang": r["target_lang"],
                        "tier": tr,
                        "per_word": str(r["per_word"]),
                    }
                )
        cur = found.currency or "EUR"
        name = "Standard price list"
        data: dict[str, Any] = {"name": name, "currency": cur, "rates": rates}
        if found.minimum is not None:
            data["minimum_charge"] = str(found.minimum)
        rates_txt = ", ".join(
            f"{r['per_word']} {cur}/word ({r['tier']}"
            + (
                f", {r['source_lang'] or '*'}-{r['target_lang'] or '*'}"
                if r["source_lang"] or r["target_lang"]
                else ""
            )
            + ")"
            for r in rates
        )
        plan.append(
            {
                "type": "create_price_list",
                "summary": f'Price list "{name}": ' + rates_txt,
                "data": data,
            }
        )
        pl_ref = len(plan) - 1
        if not found.langs_mentioned:
            questions.append(
                "Which language pairs do you work in? I set the rate for all pairs for now; I can add per-pair rates."
            )
    elif kinds or found.clients:
        questions.append(
            "What do you charge per word (and does it differ by language pair or service level)?"
        )

    # 4. accounts
    for name, industry in found.clients:
        data = {"name": name, "kind": "client"}
        if industry:
            data["industry"] = industry
        if found.currency:
            data["currency"] = found.currency
        wf_ref = domain_ref if (domain_ref is not None and industry == domain) else main_ref
        if wf_ref is not None:
            data["workflow_template_id"] = f"@{wf_ref}"
        if pl_ref is not None:
            data["price_list_id"] = f"@{pl_ref}"
        extra = []
        if industry:
            extra.append(industry)
        if wf_ref is not None and wf_ref == domain_ref:
            extra.append("stricter workflow")
        plan.append(
            {
                "type": "create_account",
                "summary": f'Client "{name}"' + (f" ({', '.join(extra)})" if extra else ""),
                "data": data,
            }
        )
    if not found.clients and (kinds or found.rates or found.agency):
        questions.append(
            "Who are your main clients? Give me their names (and contact e-mails if you want contacts added)."
        )
    elif found.clients and not found.contacts_hint:
        notes.append("I did not add contacts because no names or e-mail addresses were given.")

    # 5. dashboard
    if found.wants_dashboard:
        metrics = found.metrics or DEFAULT_DASHBOARD
        metrics = sorted(dict.fromkeys(metrics), key=lambda w: TYPE_ORDER[w[0]])
        widgets = [
            {
                "type": wt,
                "metric": m,
                "size": "s" if wt == "kpi" else ("l" if wt in ("line", "table") else "m"),
            }
            for wt, m in metrics
        ]
        name = "Business overview"
        plan.append(
            {
                "type": "create_dashboard",
                "summary": f'Dashboard "{name}": ' + ", ".join(m for _, m in metrics),
                "data": {"name": name, "widgets": widgets},
            }
        )

    if found.team:
        notes.append(
            "Reviewers join through the reviewer community (apply, test, approval); I cannot create them from here. "
            "Invite your team to apply at /reviewers/apply."
        )
    if plan and not found.agency and not org_data.get("name") and found.agency_kind:
        questions.append("What is your agency called?")

    if not plan:
        return _localized(answer_question(text, context), locale), []

    lines = ["Here is a proposed setup based on your description:"]
    lines += [f"{i + 1}. {a['summary']}" for i, a in enumerate(plan)]
    if notes:
        lines.append("")
        lines += [f"- {n}" for n in notes]
    if questions:
        lines.append("")
        lines.append("To finish the setup:")
        lines += [f"- {q}" for q in questions]
    lines.append("")
    lines.append("Nothing changes until you apply the plan (all of it or only selected actions).")
    return _localized("\n".join(lines), locale), plan


LOCALE_NOTE = (
    "(This answer is in English: the built-in planner always answers in English. "
    "Replies in {locale} come from the AI model when one is configured.)"
)


def _localized(reply: str, locale: str) -> str:
    """English-first: a non-English locale gets the English reply plus a note."""
    base = (locale or "en").split("-")[0].lower()
    return reply if base == "en" else f"{reply}\n\n{LOCALE_NOTE.format(locale=locale)}"


# ----------------------------------------------------------------------------- data questions


def answer_question(text: str, context: dict[str, Any]) -> str:
    """Answer a question about the org's data from the context summary only."""
    f = fold(text)
    jobs = context.get("jobs") or {}
    cur = context.get("currency") or "EUR"
    out: list[str] = []
    if re.search(r"\bkasn\w*|\boverdue\b|\blate\b|\brok\w*|\bdeadline\w*|\bzakasn\w*", f):
        n = int(jobs.get("overdue") or 0)
        out.append(
            "No job is overdue."
            if n == 0
            else (f"{n} job is overdue." if n == 1 else f"{n} jobs are overdue.")
        )
        for j in (jobs.get("overdue_list") or [])[:5]:
            who = ", ".join(x for x in (j.get("project"), j.get("account"), j.get("target_lang")) if x)
            out.append(
                f"- {j.get('job_id')} ({who}): " + f"due {j.get('due_at')}, {j.get('hours_overdue')} h late"
            )
    if re.search(r"\baktivn\w*|\bu\s+toku\b|\bactive\b|\bin\s+progress\b|\brunning\b", f):
        out.append(f"Active jobs: {jobs.get('active', 0)}.")
    if re.search(r"\bprihod\w*|\bzarad\w*|\brevenue\b|\bincome\b|\bturnover\b|\bpromet\w*|\bearn\w*", f):
        out.append(
            f"Revenue in the last 90 days: {context.get('revenue_90d', '0.00')} {cur} (margin {context.get('margin_90d', '0.00')} {cur})."
        )
    elif re.search(r"\bmarz\w*|\bmargin\w*|\bprofit\w*|\bdobit\w*", f):
        out.append(f"Margin in the last 90 days: {context.get('margin_90d', '0.00')} {cur}.")
    if re.search(r"\bdeal\w*|\bponud\w*|\bprodaj\w*|\bpipeline\b|\bsales\b|\bleads?\b|\bprilik\w*", f):
        deals = context.get("deals") or {}
        stages = ", ".join(
            f"{st}: {v.get('count', 0)}" for st, v in (deals.get("by_stage") or {}).items() if v.get("count")
        )
        out.append(
            f"Open deals are worth {deals.get('open_value', '0.00')} {cur}"
            + (f" ({stages})." if stages else ".")
        )
    if re.search(r"\bklijen\w*|\bclients?\b|\baccounts?\b|\bcustomers?\b|\bkupc\w*", f):
        acc = context.get("accounts") or {}
        names = ", ".join(acc.get("names") or [])
        out.append(f"Clients: {acc.get('active', 0)}" + (f" ({names})." if names else "."))
    if re.search(r"\bworkflow\w*|\btok\w*\s+rada|\bproces\w*", f):
        names = ", ".join(w.get("name", "") for w in context.get("workflows") or [])
        out.append(f"Workflows: {names or 'none yet'}.")
    if re.search(r"\bcen\w*|\bprice\w*|\brates?\b|\bcenovnik\w*", f):
        names = ", ".join(p.get("name", "") for p in context.get("price_lists") or [])
        out.append(f"Price lists: {names or 'none yet'}.")
    if not out:
        out.append(
            f"Right now: {jobs.get('active', 0)} active jobs, {jobs.get('overdue', 0)} overdue, "
            f"revenue 90 days {context.get('revenue_90d', '0.00')} {cur}, "
            f"{(context.get('accounts') or {}).get('active', 0)} clients. "
            "Ask me something specific, or describe your agency (clients, workflow, prices, reports) and I will propose a setup."
        )
    return "\n".join(out)
