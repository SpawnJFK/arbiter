"""Sentence segmentation over tagged content.

Rules:
- boundaries come from pysbd (rule based, 20+ languages, MIT) on the plain text;
- a boundary is accepted only where paired inline codes are balanced (depth 0), so a
  bold span is never cut in half;
- whitespace between sentences is kept on the previous segment as trailing_ws and
  restored on merge;
- a unit that is only whitespace, numbers or punctuation is not segmented.

pysbd is used instead of SRX because no maintained SRX engine exists for Python.
The interface is the same either way, so an SRX implementation can replace this
module without touching callers. See decisions.md D-007.
"""

from __future__ import annotations

import re
from functools import lru_cache

from arbiter.fileproc.base import Content, InlineCode, SegmentDraft

try:  # pysbd emits SyntaxWarnings on 3.12+; harmless
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import pysbd
except Exception:  # pragma: no cover
    pysbd = None  # type: ignore[assignment]

# pysbd language codes we can use directly
_PYSBD_LANGS = {
    "en",
    "hi",
    "mr",
    "zh",
    "es",
    "am",
    "ar",
    "hy",
    "bg",
    "ur",
    "ru",
    "pl",
    "fa",
    "nl",
    "da",
    "fr",
    "my",
    "el",
    "it",
    "ja",
    "de",
    "kk",
    "sk",
}
# closest pysbd ruleset for languages it does not ship
_FALLBACK = {
    "sr": "ru",
    "hr": "pl",
    "bs": "pl",
    "sl": "pl",
    "cs": "sk",
    "uk": "ru",
    "mk": "bg",
    "pt": "es",
    "ro": "it",
    "sv": "da",
    "no": "da",
    "nb": "da",
    "fi": "da",
    "et": "da",
    "lv": "pl",
    "lt": "pl",
    "hu": "de",
    "tr": "en",
    "ko": "ja",
}

_NON_TEXT = re.compile(r"^[\s\d\W_]*$", re.UNICODE)

# SRX-style exception rules: never break after these abbreviations. Lowercased, without the dot.
_ABBREV: dict[str, set[str]] = {
    "sr": {
        "npr",
        "tj",
        "itd",
        "sl",
        "dr",
        "br",
        "str",
        "god",
        "čl",
        "cl",
        "st",
        "gl",
        "mr",
        "prof",
        "ing",
        "ul",
        "tel",
        "tzv",
        "odn",
        "napr",
        "sv",
        "gosp",
        "gđa",
        "gdja",
        "dipl",
        "v.d",
        "jan",
        "feb",
        "mar",
        "apr",
        "avg",
        "sept",
        "okt",
        "nov",
        "dec",
        "наp",
        "нпр",
        "тј",
        "итд",
        "сл",
        "др",
        "бр",
        "стр",
        "год",
    },
    "hr": {
        "npr",
        "tj",
        "itd",
        "sl",
        "dr",
        "br",
        "str",
        "god",
        "čl",
        "st",
        "mr",
        "prof",
        "ing",
        "ul",
        "tzv",
        "odn",
        "sv",
        "dipl",
        "tel",
    },
    "bs": {"npr", "tj", "itd", "sl", "dr", "br", "str", "god", "čl", "st", "mr", "prof", "ing"},
    "sl": {"npr", "tj", "itd", "dr", "št", "str", "mag", "prof", "ul", "tel", "oz", "t.i"},
    "cs": {"např", "tj", "atd", "apod", "str", "č", "dr", "ing", "mgr", "prof", "ul", "tzv", "resp"},
    "sk": {"napr", "tj", "atď", "str", "č", "dr", "ing", "mgr", "prof", "ul", "tzv"},
    "pl": {"np", "tj", "itd", "itp", "dr", "str", "nr", "ul", "prof", "mgr", "inż", "tzw", "godz", "r", "ok"},
    "ru": {"т.е", "т.д", "т.п", "др", "стр", "г", "гг", "им", "ул", "тел", "см", "напр", "проф"},
    "uk": {"т.я", "т.д", "т.п", "др", "стор", "р", "вул", "тел", "див", "напр", "проф"},
    "de": {"z.b", "bzw", "usw", "ca", "dr", "nr", "s", "str", "vgl", "evtl", "ggf", "inkl", "d.h", "u.a"},
    "fi": {"esim", "ns", "mm", "yms", "jne", "tms", "ks", "nro", "puh", "klo"},
    "hu": {"pl", "stb", "ill", "kb", "dr", "u", "sz", "vö", "ún"},
    "tr": {"vb", "vs", "dr", "prof", "doç", "sn", "örn", "bkz"},
    "en": {"e.g", "i.e", "etc", "vs", "dr", "mr", "mrs", "ms", "prof", "no", "fig", "approx", "inc", "ltd"},
}


def _abbrev_for(lang: str) -> set[str]:
    base = lang.split("-")[0].split("_")[0].lower()
    return _ABBREV.get(base, set())


def _filter_cuts(text: str, cuts: list[int], lang: str) -> list[int]:
    """Drop boundaries that follow a known abbreviation or precede a lowercase word."""
    abbrevs = _abbrev_for(lang)
    kept = []
    for c in cuts:
        before = text[:c].rstrip()
        after = text[c:].lstrip()
        if after[:1].islower():
            continue  # "Npr. za 3 dana" is one sentence
        if before.endswith("."):
            word = re.split(r"[\s(\[\"'«„]", before[:-1])[-1].lower()
            if word in abbrevs:
                continue
        kept.append(c)
    return kept


@lru_cache(maxsize=64)
def _seg_for(lang: str):
    base = lang.split("-")[0].split("_")[0].lower()
    code = base if base in _PYSBD_LANGS else _FALLBACK.get(base, "en")
    if pysbd is None:
        return None
    return pysbd.Segmenter(language=code, clean=False, char_span=True)


def _boundaries(text: str, lang: str) -> list[int]:
    """Return character offsets in `text` where a new sentence starts (excluding 0)."""
    seg = _seg_for(lang)
    if seg is None or len(text) < 2:
        return []
    try:
        spans = seg.segment(text)
    except Exception:
        return []
    starts = []
    for span in spans[1:]:
        start = getattr(span, "start", None)
        if start is not None and 0 < start < len(text):
            starts.append(start)
    return starts


def segment(content: Content, lang: str) -> list[SegmentDraft]:
    """Split one unit's content into segments."""
    plain = "".join(r for r in content if isinstance(r, str))
    if not plain.strip() or _NON_TEXT.match(plain):
        return [SegmentDraft(content=list(content))] if content else []

    cuts = set(_filter_cuts(plain, _boundaries(plain, lang), lang))
    if not cuts:
        return [SegmentDraft(content=list(content))]

    # Walk runs, tracking plain-text offset and code depth; cut only at depth 0.
    segments: list[list] = [[]]
    offset, depth = 0, 0
    for run in content:
        if isinstance(run, InlineCode):
            segments[-1].append(run)
            if run.kind == "open":
                depth += 1
            elif run.kind == "close":
                depth = max(0, depth - 1)
            continue
        text = run
        start = 0
        for i in range(len(text)):
            if (offset + i) in cuts and depth == 0:
                piece = text[start:i]
                if piece:
                    segments[-1].append(piece)
                if segments[-1]:  # never open an empty segment
                    segments.append([])
                start = i
        if start < len(text):
            segments[-1].append(text[start:])
        offset += len(text)

    drafts: list[SegmentDraft] = []
    for seg in segments:
        if not seg:
            continue
        drafts.append(SegmentDraft(content=seg))

    # Move whitespace at segment ends into trailing_ws, and leading whitespace of the
    # next segment onto the previous one's trailing_ws.
    for idx, d in enumerate(drafts):
        # leading ws -> previous trailing
        if idx > 0 and d.content and isinstance(d.content[0], str):
            stripped = d.content[0].lstrip()
            lead = d.content[0][: len(d.content[0]) - len(stripped)]
            if lead:
                drafts[idx - 1].trailing_ws += lead
                if stripped:
                    d.content[0] = stripped
                else:
                    d.content.pop(0)
        # trailing ws
        if d.content and isinstance(d.content[-1], str):
            stripped = d.content[-1].rstrip()
            trail = d.content[-1][len(stripped) :]
            if trail:
                d.trailing_ws = trail + d.trailing_ws
                if stripped:
                    d.content[-1] = stripped
                else:
                    d.content.pop()
    return [d for d in drafts if d.content or d.trailing_ws]


def segment_unit_text(text: str, lang: str) -> list[SegmentDraft]:
    return segment([text], lang)
