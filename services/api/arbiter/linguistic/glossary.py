"""Glossaries: versioned term storage, term detection in source, term checks on target.

Rules implemented here
- R-GL-01 Term kinds: mandatory (error when missing), preferred (warning), forbidden
  (error when present in target), do_not_translate (target keeps the source string).
- R-GL-03 Matching is lemmatized: inflected forms satisfy a term (lemma.stem).
- R-GL-04 Languages match by primary subtag ("sr-Latn" term applies to an "sr" job).
- R-GL-05 Overlapping matches: the longest wins ("payment terms" beats "payment").
- R-GL-06 Occurrences count: a mandatory term used twice in the source must appear
  at least twice in the target.
- R-GL-07 DNT checks are char-exact, never transliterated or stemmed.
- R-GL-11 Versions are temporal and org-wide monotone. Every change bumps the
  version; a term is valid for [valid_from, valid_to). A job freezes
  current_version() at start, so a glossary edited mid-job never changes that job.
  The counter is org-wide (not per glossary) so that one frozen number is
  meaningful across all glossaries a job uses.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from lxml import etree  # type: ignore[import-untyped]
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from arbiter.contracts import TermHit, TermViolation
from arbiter.linguistic.lemma import norm_lang, primary_lang, stem, stems_match, tokenize
from arbiter.models import Glossary, Term

TERM_KINDS = ("mandatory", "preferred", "forbidden", "do_not_translate")
_KIND_PRIORITY = {"do_not_translate": 0, "mandatory": 1, "preferred": 2, "forbidden": 3}


# ============================================================== versioning + CRUD


def _lang_matches(column: Any, lang: str) -> Any:
    """SQL predicate: column's primary subtag equals lang's primary subtag (R-GL-04)."""
    p = primary_lang(lang)
    col = func.lower(func.replace(column, "_", "-"))
    return or_(col == p, col.like(f"{p}-%"))


def _org_max_version(session: Session, org_id: str, *, lock: bool = False) -> int:
    stmt = select(Glossary.version).where(Glossary.org_id == org_id)
    if lock:
        stmt = stmt.with_for_update()
    versions = list(session.execute(stmt).scalars())
    return max(versions, default=0)


def _bump(session: Session, glossary: Glossary) -> int:
    """Next org-wide version, assigned to this glossary (R-GL-11)."""
    new_version = _org_max_version(session, glossary.org_id, lock=True) + 1
    glossary.version = new_version
    session.flush()
    return new_version


def create_glossary(session: Session, org_id: str, name: str, content_type: str | None = None) -> Glossary:
    """New empty glossary. Starts at the org's current version: creating it changes no term."""
    g = Glossary(
        org_id=org_id, name=name, content_type=content_type, version=max(1, _org_max_version(session, org_id))
    )
    session.add(g)
    session.flush()
    return g


def _applicable_glossaries(org_id: str, content_type: str | None) -> Select[Any]:
    stmt = select(Glossary.id).where(Glossary.org_id == org_id)
    if content_type is not None:
        stmt = stmt.where(or_(Glossary.content_type.is_(None), Glossary.content_type == content_type))
    else:
        stmt = stmt.where(Glossary.content_type.is_(None))
    return stmt


def current_version(session: Session, org_id: str, content_type: str | None) -> int:
    """The version a job freezes at start: max version across the applicable glossaries."""
    stmt = select(func.max(Glossary.version)).where(
        Glossary.id.in_(_applicable_glossaries(org_id, content_type))
    )
    return int(session.execute(stmt).scalar() or 0)


def active_terms(
    session: Session,
    org_id: str,
    source_lang: str,
    target_lang: str,
    content_type: str | None,
    version: int | None = None,
) -> list[Term]:
    """Terms valid for the language pair and content type at `version` (None = current).

    Glossaries with content_type NULL apply to everything; others only to their type.
    """
    stmt = select(Term).where(
        Term.glossary_id.in_(_applicable_glossaries(org_id, content_type)),
        _lang_matches(Term.source_lang, source_lang),
        _lang_matches(Term.target_lang, target_lang),
    )
    if version is None:
        stmt = stmt.where(Term.valid_to.is_(None))
    else:
        stmt = stmt.where(Term.valid_from <= version, or_(Term.valid_to.is_(None), Term.valid_to > version))
    terms = list(session.execute(stmt).scalars())
    terms.sort(key=lambda t: (-len(t.source_term), t.source_term, t.id))
    return terms


def _check_kind(kind: str) -> str:
    if kind not in TERM_KINDS:
        raise ValueError(f"unknown term kind {kind!r}; expected one of {', '.join(TERM_KINDS)}")
    return kind


def _new_term(
    glossary: Glossary,
    version: int,
    *,
    source_lang: str,
    target_lang: str,
    source_term: str,
    target_term: str | None,
    kind: str,
    case_sensitive: bool,
    note: str,
) -> Term:
    _check_kind(kind)
    source_term = (source_term or "").strip()
    if not source_term:
        raise ValueError("source_term is empty")
    target_term = (target_term or "").strip() or None
    if kind == "do_not_translate":
        target_term = None
    if kind in ("mandatory", "preferred") and target_term is None:
        raise ValueError(f"{kind} term {source_term!r} needs a target term")
    return Term(
        glossary_id=glossary.id,
        source_lang=norm_lang(source_lang),
        target_lang=norm_lang(target_lang),
        source_term=source_term,
        target_term=target_term,
        kind=kind,
        case_sensitive=bool(case_sensitive),
        note=note or "",
        valid_from=version,
        valid_to=None,
    )


def add_term(
    session: Session,
    glossary_id: str,
    source_lang: str,
    target_lang: str,
    source_term: str,
    target_term: str | None,
    kind: str = "mandatory",
    *,
    case_sensitive: bool = False,
    note: str = "",
) -> Term:
    """Add a term; bumps the version so jobs already running do not see it.

    Forbidden terms: target_term is the forbidden target string (falls back to
    source_term when None, for plain target-language blocklists).
    """
    glossary = session.get(Glossary, glossary_id)
    if glossary is None:
        raise ValueError(f"glossary {glossary_id} not found")
    v = _bump(session, glossary)
    term = _new_term(
        glossary,
        v,
        source_lang=source_lang,
        target_lang=target_lang,
        source_term=source_term,
        target_term=target_term,
        kind=kind,
        case_sensitive=case_sensitive,
        note=note,
    )
    session.add(term)
    session.flush()
    return term


_UPDATABLE = ("source_lang", "target_lang", "source_term", "target_term", "kind", "case_sensitive", "note")


def update_term(session: Session, term_id: str, **changes: Any) -> Term:
    """Change a term by closing the current row and inserting a new one (history kept)."""
    unknown = set(changes) - set(_UPDATABLE)
    if unknown:
        raise ValueError(f"cannot update {sorted(unknown)}")
    old = session.get(Term, term_id)
    if old is None or old.valid_to is not None:
        raise ValueError(f"term {term_id} not found or already retired")
    glossary = session.get(Glossary, old.glossary_id)
    assert glossary is not None
    v = _bump(session, glossary)
    old.valid_to = v
    values = {k: getattr(old, k) for k in _UPDATABLE}
    values.update(changes)
    new = _new_term(glossary, v, **values)
    session.add(new)
    session.flush()
    return new


def retire_term(session: Session, term_id: str) -> Term:
    """Close a term at a new version; jobs frozen earlier still see it."""
    term = session.get(Term, term_id)
    if term is None or term.valid_to is not None:
        raise ValueError(f"term {term_id} not found or already retired")
    glossary = session.get(Glossary, term.glossary_id)
    assert glossary is not None
    term.valid_to = _bump(session, glossary)
    session.flush()
    return term


# ============================================================== matching


@dataclass(frozen=True)
class _Tok:
    surface: str
    stem: str
    start: int
    end: int


def _toks(text: str, lang: str) -> list[_Tok]:
    return [_Tok(s, stem(s, lang), a, b) for s, a, b in tokenize(text)]


def _case_ok(tok: str, pat: str, pat_stem: str) -> bool:
    """Case-sensitive terms: the stem part must have the same upper/lower pattern.

    Compared positionally on isupper() so it also works across Serbian scripts.
    """
    k = min(len(tok), len(pat), max(1, len(pat_stem)))
    return [c.isupper() for c in tok[:k]] == [c.isupper() for c in pat[:k]]


def _seq_at(toks: Sequence[_Tok], i: int, pat: Sequence[_Tok], lang: str, case_sensitive: bool) -> bool:
    if i + len(pat) > len(toks):
        return False
    for t, p in zip(toks[i : i + len(pat)], pat, strict=False):
        if not stems_match(t.stem, p.stem, lang):
            return False
        if case_sensitive and not _case_ok(t.surface, p.surface, p.stem):
            return False
    return True


def _find_spans(
    toks: Sequence[_Tok], pat: Sequence[_Tok], lang: str, case_sensitive: bool
) -> list[tuple[int, int]]:
    """Non-overlapping token-index spans where `pat` occurs."""
    out: list[tuple[int, int]] = []
    if not pat:
        return out
    i = 0
    while i <= len(toks) - len(pat):
        if _seq_at(toks, i, pat, lang, case_sensitive):
            out.append((i, i + len(pat)))
            i += len(pat)
        else:
            i += 1
    return out


def count_occurrences(text: str, phrase: str, lang: str, case_sensitive: bool = False) -> int:
    """How many times `phrase` occurs in `text`, inflected forms included."""
    return len(_find_spans(_toks(text, lang), _toks(phrase, lang), lang, case_sensitive))


def forbidden_string(term: Any) -> str:
    return term.target_term or term.source_term


def find_source_terms(source_plain: str, terms: Iterable[Term], source_lang: str) -> list[TermHit]:
    """Glossary terms found in a source segment, plus every forbidden term.

    Forbidden terms are target-side: they are returned with start=end=-1 whether or
    not the source mentions them, so checkers and engines watch the target (R-GL-01).
    """
    toks = _toks(source_plain, source_lang)
    by_key: dict[str, list[int]] = defaultdict(list)
    for idx, t in enumerate(toks):
        by_key[t.stem[:3]].append(idx)

    candidates: list[tuple[int, int, int, Term]] = []  # (start_char, end_char, n_tokens, term)
    forbidden: list[TermHit] = []
    for term in terms:
        if term.kind == "forbidden":
            forbidden.append(
                TermHit(
                    term_id=term.id,
                    kind="forbidden",
                    source_term=term.source_term,
                    target_term=forbidden_string(term),
                    start=-1,
                    end=-1,
                    case_sensitive=bool(term.case_sensitive),
                    note=term.note or "",
                )
            )
            continue
        pat = _toks(term.source_term, source_lang)
        if not pat:
            continue
        for i in by_key.get(pat[0].stem[:3], ()):
            if _seq_at(toks, i, pat, source_lang, bool(term.case_sensitive)):
                last = toks[i + len(pat) - 1]
                candidates.append((toks[i].start, last.end, len(pat), term))

    # Longest match wins; on equal length the earlier one, then the stronger kind (R-GL-05).
    candidates.sort(key=lambda c: (-(c[1] - c[0]), c[0], _KIND_PRIORITY.get(c[3].kind, 9)))
    taken: list[tuple[int, int]] = []
    hits: list[TermHit] = []
    for start, end, _n, term in candidates:
        if any(start < e and s < end for s, e in taken):
            continue
        taken.append((start, end))
        hits.append(
            TermHit(
                term_id=term.id,
                kind=term.kind,  # type: ignore[arg-type]
                source_term=term.source_term,
                target_term=None if term.kind == "do_not_translate" else term.target_term,
                start=start,
                end=end,
                case_sensitive=bool(term.case_sensitive),
                note=term.note or "",
            )
        )
    hits.sort(key=lambda h: h.start)
    return hits + forbidden


def _count_exact(text: str, needle: str, case_sensitive: bool) -> int:
    if not needle:
        return 0
    if case_sensitive:
        return text.count(needle)
    return text.lower().count(needle.lower())


def check_target(target_plain: str, hits: Sequence[TermHit], target_lang: str) -> list[TermViolation]:
    """Check a target against the hits found in its source (R-GL-01/06/07)."""
    toks = _toks(target_plain, target_lang)
    groups: dict[str, list[TermHit]] = defaultdict(list)
    for h in hits:
        groups[h.term_id].append(h)

    out: list[TermViolation] = []
    for term_id, group in groups.items():
        h = group[0]
        if h.kind == "forbidden":
            needle = h.target_term or h.source_term
            pat = _toks(needle, target_lang)
            if _find_spans(toks, pat, target_lang, h.case_sensitive):
                out.append(
                    TermViolation(
                        term_id, "forbidden", "term_forbidden", "error", f"Forbidden term '{needle}' used"
                    )
                )
            continue

        need = sum(1 for g in group if g.start >= 0)
        if need == 0:
            continue
        if h.kind == "do_not_translate":
            found = _count_exact(target_plain, h.source_term, h.case_sensitive)
            if found < need:
                out.append(
                    TermViolation(
                        term_id,
                        "do_not_translate",
                        "dnt_changed",
                        "error",
                        f"'{h.source_term}' must stay untranslated and unchanged"
                        + (f" ({found} of {need} occurrences kept)" if found else ""),
                    )
                )
            continue

        if not h.target_term:
            continue
        found = len(_find_spans(toks, _toks(h.target_term, target_lang), target_lang, h.case_sensitive))
        if found >= need:
            continue
        detail = f" ({found} of {need} occurrences)" if found else ""
        if h.kind == "mandatory":
            out.append(
                TermViolation(
                    term_id,
                    "mandatory",
                    "term_missing",
                    "error",
                    f"'{h.source_term}' must be translated as '{h.target_term}'{detail}",
                )
            )
        elif h.kind == "preferred":
            out.append(
                TermViolation(
                    term_id,
                    "preferred",
                    "term_preferred_missing",
                    "warning",
                    f"Preferred translation of '{h.source_term}' is '{h.target_term}'{detail}",
                )
            )
    return out


# ============================================================== import / export

_CSV_COLUMNS = ("source_lang", "target_lang", "source_term", "target_term", "kind", "case_sensitive", "note")
_HEADER_ALIASES: dict[str, str] = {}
for _canon, _aliases in {
    "source_lang": ("source_lang", "source_language", "src_lang", "srclang", "source_locale", "from"),
    "target_lang": (
        "target_lang",
        "target_language",
        "tgt_lang",
        "trg_lang",
        "tgtlang",
        "target_locale",
        "to",
    ),
    "source_term": ("source_term", "source", "src", "term", "source_text", "src_term"),
    "target_term": ("target_term", "target", "tgt", "translation", "target_text", "tgt_term", "trg"),
    "kind": ("kind", "type", "status", "term_type", "usage"),
    "case_sensitive": ("case_sensitive", "case", "match_case", "casesensitive", "case_sens"),
    "note": ("note", "notes", "comment", "comments", "description", "definition"),
}.items():
    for _a in _aliases:
        _HEADER_ALIASES[_a] = _canon

_KIND_ALIASES = {
    "": "mandatory",
    "mandatory": "mandatory",
    "required": "mandatory",
    "approved": "mandatory",
    "preferred": "preferred",
    "admitted": "preferred",
    "recommended": "preferred",
    "forbidden": "forbidden",
    "deprecated": "forbidden",
    "prohibited": "forbidden",
    "banned": "forbidden",
    "do_not_translate": "do_not_translate",
    "dnt": "do_not_translate",
    "untranslatable": "do_not_translate",
    "notranslate": "do_not_translate",
}


def _norm_header(h: str) -> str:
    key = h.strip().lstrip("﻿").lower().replace("-", "_").replace(" ", "_")
    return _HEADER_ALIASES.get(key, key)


def _norm_kind(value: str) -> str:
    key = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if key in _KIND_ALIASES:
        return _KIND_ALIASES[key]
    raise ValueError(f"unknown kind {value!r}")


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "y", "x", "t")


@dataclass
class _Row:
    source_lang: str
    target_lang: str
    source_term: str
    target_term: str | None
    kind: str
    case_sensitive: bool
    note: str


def _apply_rows(
    session: Session, glossary: Glossary, rows: list[tuple[int, _Row]], errors: list[str]
) -> dict:
    """Write rows at one new version. Identical active terms are skipped; a changed
    target/flags for the same (pair, source term, kind) supersedes the old row."""
    existing: dict[tuple[str, str, str, str], Term] = {}
    for t in session.execute(
        select(Term).where(Term.glossary_id == glossary.id, Term.valid_to.is_(None))
    ).scalars():
        existing[
            (primary_lang(t.source_lang), primary_lang(t.target_lang), t.source_term.lower(), t.kind)
        ] = t

    imported = skipped = 0
    version: int | None = None
    for lineno, r in rows:
        key = (
            primary_lang(r.source_lang),
            primary_lang(r.target_lang),
            r.source_term.strip().lower(),
            r.kind,
        )
        old = existing.get(key)
        tgt = (r.target_term or "").strip() or None
        if r.kind == "do_not_translate":
            tgt = None
        if (
            old is not None
            and old.target_term == tgt
            and old.case_sensitive == r.case_sensitive
            and (old.note or "") == r.note
        ):
            skipped += 1
            continue
        if version is None:
            version = _bump(session, glossary)
        try:
            term = _new_term(
                glossary,
                version,
                source_lang=r.source_lang,
                target_lang=r.target_lang,
                source_term=r.source_term,
                target_term=r.target_term,
                kind=r.kind,
                case_sensitive=r.case_sensitive,
                note=r.note,
            )
        except ValueError as e:
            errors.append(f"row {lineno}: {e}")
            continue
        if old is not None:
            old.valid_to = version
        session.add(term)
        existing[key] = term
        imported += 1
    session.flush()
    return {"imported": imported, "skipped": skipped, "errors": errors}


def import_csv(
    session: Session,
    glossary_id: str,
    data: bytes | str,
    *,
    source_lang: str | None = None,
    target_lang: str | None = None,
) -> dict:
    """Import a CSV/TSV glossary. Delimiter is sniffed, header names are tolerant.

    source_lang/target_lang are defaults for files without language columns.
    Returns {imported, skipped, errors}; one new version for the whole file.
    """
    glossary = session.get(Glossary, glossary_id)
    if glossary is None:
        raise ValueError(f"glossary {glossary_id} not found")
    text = data.decode("utf-8-sig", errors="replace") if isinstance(data, bytes) else data.lstrip("﻿")
    sample = text[:4096]
    try:
        dialect: Any = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    errors: list[str] = []
    try:
        header = [_norm_header(h) for h in next(reader)]
    except StopIteration:
        return {"imported": 0, "skipped": 0, "errors": ["empty file"]}
    if "source_term" not in header:
        return {"imported": 0, "skipped": 0, "errors": ["no source term column in header"]}

    rows: list[tuple[int, _Row]] = []
    for lineno, raw in enumerate(reader, start=2):
        if not any(c.strip() for c in raw):
            continue
        rec = {header[i]: raw[i].strip() for i in range(min(len(header), len(raw)))}
        try:
            sl = rec.get("source_lang") or source_lang
            tl = rec.get("target_lang") or target_lang
            if not sl or not tl:
                raise ValueError("language missing")
            if not rec.get("source_term"):
                raise ValueError("source term empty")
            rows.append(
                (
                    lineno,
                    _Row(
                        source_lang=sl,
                        target_lang=tl,
                        source_term=rec["source_term"],
                        target_term=rec.get("target_term") or None,
                        kind=_norm_kind(rec.get("kind", "")),
                        case_sensitive=_truthy(rec.get("case_sensitive")),
                        note=rec.get("note", ""),
                    ),
                )
            )
        except ValueError as e:
            errors.append(f"row {lineno}: {e}")
    return _apply_rows(session, glossary, rows, errors)


def _glossary_terms(session: Session, glossary_id: str, version: int | None) -> list[Term]:
    stmt = select(Term).where(Term.glossary_id == glossary_id)
    if version is None:
        stmt = stmt.where(Term.valid_to.is_(None))
    else:
        stmt = stmt.where(Term.valid_from <= version, or_(Term.valid_to.is_(None), Term.valid_to > version))
    return list(session.execute(stmt.order_by(Term.source_term, Term.id)).scalars())


def export_csv(session: Session, glossary_id: str, version: int | None = None) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(_CSV_COLUMNS)
    for t in _glossary_terms(session, glossary_id, version):
        w.writerow(
            [
                t.source_lang,
                t.target_lang,
                t.source_term,
                t.target_term or "",
                t.kind,
                "true" if t.case_sensitive else "false",
                t.note or "",
            ]
        )
    return buf.getvalue()


# ---------------------------------------------------------------- TBX

_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_TBX3_NS = "urn:iso:std:iso:30042:ed-2"
_STATUS_FOR_KIND = {
    "mandatory": "preferredTerm-admn-sts",
    "do_not_translate": "preferredTerm-admn-sts",
    "preferred": "admittedTerm-admn-sts",
    "forbidden": "deprecatedTerm-admn-sts",
}


def _secure_parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=True, huge_tree=False)


def _local(el: Any) -> str:
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def _children(el: Any, *names: str) -> list[Any]:
    return [c for c in el if _local(c) in names]


def _descendants(el: Any, *names: str) -> list[Any]:
    return [c for c in el.iter() if _local(c) in names]


def _kind_from_status(status: str) -> str:
    s = status.lower()
    if any(x in s for x in ("deprecated", "superseded", "notrecommended", "forbidden")):
        return "forbidden"
    if "admitted" in s:
        return "preferred"
    return "mandatory"


def _tbx_terms(lang_el: Any) -> list[dict[str, Any]]:
    """Terms of one langSet/langSec with their notes, for TBX v2 (tig/ntig) and v3 (termSec)."""
    out: list[dict[str, Any]] = []
    for holder in _children(lang_el, "tig", "ntig", "termSec"):
        term_els = _descendants(holder, "term")
        if not term_els:
            continue
        text = "".join(term_els[0].itertext()).strip()
        if not text:
            continue
        notes: dict[str, str] = {}
        for tn in _descendants(holder, "termNote", "descrip", "admin"):
            notes[(tn.get("type") or "").strip()] = "".join(tn.itertext()).strip()
        note_texts = ["".join(n.itertext()).strip() for n in _descendants(holder, "note")]
        out.append({"term": text, "notes": notes, "note": "; ".join(t for t in note_texts if t)})
    return out


def import_tbx(
    session: Session,
    glossary_id: str,
    data: bytes,
    *,
    source_lang: str,
    target_langs: Iterable[str] | None = None,
) -> dict:
    """Import TBX-Basic (TBX 2008 martif) or TBX v3 (tbx/conceptEntry).

    TBX is concept oriented and multilingual: the first non-deprecated term in
    `source_lang` is paired with every term of each other language. administrative
    status maps to kind (preferred -> mandatory, admitted -> preferred, deprecated
    -> forbidden); our own x-arbiter-kind / x-arbiter-case notes override that.
    """
    glossary = session.get(Glossary, glossary_id)
    if glossary is None:
        raise ValueError(f"glossary {glossary_id} not found")
    try:
        root = etree.fromstring(data, _secure_parser())
    except etree.XMLSyntaxError as e:
        return {"imported": 0, "skipped": 0, "errors": [f"invalid XML: {e}"]}
    wanted = {primary_lang(t) for t in target_langs} if target_langs else None
    src_p = primary_lang(source_lang)
    errors: list[str] = []
    rows: list[tuple[int, _Row]] = []
    entry_skipped = 0
    for n, entry in enumerate(_descendants(root, "termEntry", "conceptEntry"), start=1):
        entry_note = "; ".join(
            "".join(d.itertext()).strip()
            for d in _children(entry, "descrip", "note")
            if "".join(d.itertext()).strip()
        )
        by_lang: list[tuple[str, list[dict[str, Any]]]] = []
        for ls in _children(entry, "langSet", "langSec"):
            lang = ls.get(_XML_LANG) or ls.get("lang") or ""
            by_lang.append((lang, _tbx_terms(ls)))
        src_terms = [
            t
            for lang, terms in by_lang
            if primary_lang(lang) == src_p
            for t in terms
            if _kind_from_status(t["notes"].get("administrativeStatus", "")) != "forbidden"
        ]
        if not src_terms:
            entry_skipped += 1
            continue
        src = src_terms[0]
        for lang, terms in by_lang:
            p = primary_lang(lang)
            if p == src_p or (wanted is not None and p not in wanted):
                continue
            for t in terms:
                kind = t["notes"].get("x-arbiter-kind") or _kind_from_status(
                    t["notes"].get("administrativeStatus", "")
                )
                try:
                    kind = _norm_kind(kind)
                except ValueError as e:
                    errors.append(f"entry {n}: {e}")
                    continue
                rows.append(
                    (
                        n,
                        _Row(
                            source_lang=source_lang,
                            target_lang=lang,
                            source_term=src["term"],
                            target_term=t["term"],
                            kind=kind,
                            case_sensitive=_truthy(t["notes"].get("x-arbiter-case")),
                            note=t["note"] or src["note"] or entry_note,
                        ),
                    )
                )
    result = _apply_rows(session, glossary, rows, errors)
    result["skipped"] += entry_skipped
    return result


def export_tbx(session: Session, glossary_id: str, version: int | None = None) -> bytes:
    """Export as TBX v3 (TBX-Basic dialect, DCA style), one conceptEntry per term."""
    terms = _glossary_terms(session, glossary_id, version)
    src_lang = terms[0].source_lang if terms else "en"
    nsmap = {None: _TBX3_NS}
    root = etree.Element(f"{{{_TBX3_NS}}}tbx", nsmap=nsmap, type="TBX-Basic", style="dca")
    root.set(_XML_LANG, src_lang)
    header = etree.SubElement(root, f"{{{_TBX3_NS}}}tbxHeader")
    fd = etree.SubElement(header, f"{{{_TBX3_NS}}}fileDesc")
    sd = etree.SubElement(fd, f"{{{_TBX3_NS}}}sourceDesc")
    etree.SubElement(sd, f"{{{_TBX3_NS}}}p").text = f"Arbiter glossary {glossary_id}"
    body = etree.SubElement(etree.SubElement(root, f"{{{_TBX3_NS}}}text"), f"{{{_TBX3_NS}}}body")

    def term_sec(parent: Any, text: str, notes: dict[str, str], note: str = "") -> None:
        ts = etree.SubElement(parent, f"{{{_TBX3_NS}}}termSec")
        etree.SubElement(ts, f"{{{_TBX3_NS}}}term").text = text
        for k, v in notes.items():
            el = etree.SubElement(ts, f"{{{_TBX3_NS}}}termNote", type=k)
            el.text = v
        if note:
            etree.SubElement(ts, f"{{{_TBX3_NS}}}note").text = note

    for i, t in enumerate(terms, start=1):
        ce = etree.SubElement(body, f"{{{_TBX3_NS}}}conceptEntry", id=f"c{i}")
        ls = etree.SubElement(ce, f"{{{_TBX3_NS}}}langSec")
        ls.set(_XML_LANG, t.source_lang)
        term_sec(ls, t.source_term, {})
        lt = etree.SubElement(ce, f"{{{_TBX3_NS}}}langSec")
        lt.set(_XML_LANG, t.target_lang)
        target = t.source_term if t.kind == "do_not_translate" else (t.target_term or t.source_term)
        notes = {"administrativeStatus": _STATUS_FOR_KIND[t.kind], "x-arbiter-kind": t.kind}
        if t.case_sensitive:
            notes["x-arbiter-case"] = "true"
        term_sec(lt, target, notes, t.note or "")
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
