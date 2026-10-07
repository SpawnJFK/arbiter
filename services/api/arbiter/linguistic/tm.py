"""Translation memory: lookup, storage, TMX import/export.

Rules implemented here
- R-TM-01 We only learn from TM the client owns: import requires rights_confirmed_by.
- R-TM-02 Only approved or imported entries are served; stale entries never are.
- R-TM-03 Match ladder: context (101, same source and same neighbours) > exact (100)
  > fuzzy (pg_trgm prefilter, rapidfuzz ratio, minus 1 per differing inline code)
  > semantic (embedding cosine, only when no fuzzy reaches min_fuzzy).
- R-TM-04 Semantic matches are examples for the engine, not leverage: callers must
  not bill or auto-insert them.
- R-TM-05 One row per (org, pair, source_hash, context_hash): a newer approved human
  translation replaces the target in place; an import never overwrites a reviewed
  translation.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from lxml import etree  # type: ignore[import-untyped]
from rapidfuzz import fuzz
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from arbiter.contracts import TmMatch
from arbiter.fileproc.base import LB, RB
from arbiter.linguistic.embeddings import embed
from arbiter.linguistic.lemma import norm_lang, primary_lang
from arbiter.models import TmEntry

SERVABLE_STATUSES = ("approved", "imported")
_WS = re.compile(r"\s+")
_TOKEN_RE = re.compile(rf"{LB}(/?)([A-Za-z0-9_.-]+)(/?){RB}")
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


# ============================================================== tagged text helpers


def _pieces(tagged: str) -> list[tuple[str, Any]]:
    """Split tagged text into ("text", str) and ("code", (id, kind)), honouring ⟦⟦ ⟧⟧ escapes.

    Lenient on purpose: a malformed token is kept as text, TM must never crash on input.
    """
    out: list[tuple[str, Any]] = []
    buf: list[str] = []
    i, n = 0, len(tagged)
    while i < n:
        ch = tagged[i]
        if ch in (LB, RB) and i + 1 < n and tagged[i + 1] == ch:
            buf.append(ch)
            i += 2
            continue
        if ch == LB:
            m = _TOKEN_RE.match(tagged, i)
            if m:
                if buf:
                    out.append(("text", "".join(buf)))
                    buf = []
                kind = "close" if m.group(1) else ("standalone" if m.group(3) else "open")
                out.append(("code", (m.group(2), kind)))
                i = m.end()
                continue
        buf.append(ch)
        i += 1
    if buf:
        out.append(("text", "".join(buf)))
    return out


def tagged_plain(tagged: str) -> str:
    """Tagged text -> plain text (codes removed, escapes resolved)."""
    return "".join(v for k, v in _pieces(tagged) if k == "text")


def _codes(tagged: str) -> Counter[tuple[str, str]]:
    return Counter(v for k, v in _pieces(tagged) if k == "code")


def _escape(text: str) -> str:
    return text.replace(LB, LB + LB).replace(RB, RB + RB)


def _normalise(text: str) -> str:
    return _WS.sub(" ", unicodedata.normalize("NFC", text or "")).strip()


def source_hash(source_tagged: str, lang: str) -> str:
    """Hash of the normalised tagged source: whitespace runs collapsed, tags kept.

    Tags are part of identity: "⟦1⟧Save⟦/1⟧" and "Save" are different segments.
    """
    return hashlib.sha256(f"{primary_lang(lang)}\x1f{_normalise(source_tagged)}".encode()).hexdigest()


def context_hash(prev_source: str | None, next_source: str | None) -> str:
    """Hash of the neighbouring source segments, for 101% in-context matches."""
    payload = f"{_normalise(prev_source or '')}\x1e{_normalise(next_source or '')}"
    return hashlib.sha256(payload.encode()).hexdigest()


# ============================================================== lookup


def _lang_clause(column: Any, lang: str) -> Any:
    p = primary_lang(lang)
    return or_(column == p, column.like(f"{p}-%"))


def _script(lang: str) -> str | None:
    for sub in norm_lang(lang).split("-")[1:]:
        if len(sub) == 4 and sub.isalpha():
            return sub
    return None


def _compatible(a: str, b: str) -> bool:
    """Same primary language, and not two different explicit scripts (sr-latn vs sr-cyrl)."""
    if primary_lang(a) != primary_lang(b):
        return False
    sa, sb = _script(a), _script(b)
    return sa is None or sb is None or sa == sb


def _tag_penalty(a: str, b: str) -> int:
    ca, cb = _codes(a), _codes(b)
    return sum(((ca - cb) + (cb - ca)).values())


def lookup(
    session: Session,
    org_id: str,
    source_lang: str,
    target_lang: str,
    source_tagged: str,
    context_hash: str | None = None,
    *,
    min_fuzzy: float = 75.0,
    limit: int = 3,
    use_semantic: bool = True,
    min_semantic: float = 60.0,
) -> list[TmMatch]:
    """Best TM matches for a segment, highest score first (R-TM-03)."""
    q_plain = tagged_plain(source_tagged)
    h = source_hash(source_tagged, source_lang)
    base = [
        TmEntry.org_id == org_id,
        TmEntry.status.in_(SERVABLE_STATUSES),
        _lang_clause(TmEntry.source_lang, source_lang),
        _lang_clause(TmEntry.target_lang, target_lang),
    ]

    def ok(e: TmEntry) -> bool:
        return _compatible(e.source_lang, source_lang) and _compatible(e.target_lang, target_lang)

    scored: list[tuple[float, str, TmEntry]] = []

    for e in session.execute(select(TmEntry).where(*base, TmEntry.source_hash == h)).scalars():
        if not ok(e):
            continue
        if context_hash is not None and e.context_hash == context_hash:
            scored.append((101.0, "context", e))
        else:
            scored.append((100.0, "exact", e))

    if q_plain.strip():
        sim = func.similarity(TmEntry.source_plain, q_plain)
        stmt = (
            select(TmEntry)
            .where(*base, TmEntry.source_hash != h, TmEntry.source_plain.op("%")(q_plain))
            .order_by(sim.desc())
            .limit(max(20, limit * 5))
        )
        for e in session.execute(stmt).scalars():
            if not ok(e):
                continue
            score = fuzz.ratio(q_plain, e.source_plain) - _tag_penalty(source_tagged, e.source_tagged)
            score = round(min(99.0, max(0.0, score)), 2)
            if score >= min_fuzzy:
                scored.append((score, "fuzzy", e))

    if use_semantic and not scored and q_plain.strip():
        qvec = embed([q_plain])[0]
        dist = TmEntry.embedding.cosine_distance(qvec)
        stmt2 = (
            select(TmEntry, dist.label("d"))
            .where(*base, TmEntry.embedding.is_not(None))
            .order_by(dist)
            .limit(max(10, limit * 3))
        )
        for e, d in session.execute(stmt2).all():
            if not ok(e):
                continue
            score = round(max(0.0, (1.0 - float(d)) * 100.0), 2)
            if score >= min_semantic:
                scored.append((min(score, 99.0), "semantic", e))

    def recency(e: TmEntry) -> float:
        return e.updated_at.timestamp() if e.updated_at else 0.0

    scored.sort(key=lambda s: (-s[0], -recency(s[2])))
    seen_ids: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    out: list[TmMatch] = []
    for score, kind, e in scored:
        pair = (e.source_tagged, e.target_tagged)
        if e.id in seen_ids or pair in seen_pairs:
            continue
        seen_ids.add(e.id)
        seen_pairs.add(pair)
        out.append(TmMatch(e.id, kind, score, e.source_tagged, e.target_tagged))  # type: ignore[arg-type]
        if len(out) >= limit:
            break
    return out


# ============================================================== storage


def _find(session: Session, org_id: str, sl: str, tl: str, shash: str, chash: str | None) -> TmEntry | None:
    stmt = select(TmEntry).where(
        TmEntry.org_id == org_id,
        TmEntry.source_lang == sl,
        TmEntry.target_lang == tl,
        TmEntry.source_hash == shash,
        TmEntry.context_hash.is_(None) if chash is None else TmEntry.context_hash == chash,
    )
    return session.execute(stmt.limit(1)).scalars().first()


def _upsert(
    session: Session,
    org_id: str,
    source_lang: str,
    target_lang: str,
    source_tagged: str,
    target_tagged: str,
    *,
    content_type: str,
    context_hash: str | None,
    origin: str,
    job_id: str | None,
    rights_confirmed_by: str | None,
    embedding: list[float] | None,
) -> tuple[TmEntry, str]:
    """Returns (entry, action) with action in inserted | updated | unchanged | kept."""
    sl, tl = norm_lang(source_lang), norm_lang(target_lang)
    shash = source_hash(source_tagged, sl)
    status = "imported" if origin == "import" else "approved"
    existing = _find(session, org_id, sl, tl, shash, context_hash)
    if existing is not None:
        if existing.target_tagged == target_tagged and existing.status in SERVABLE_STATUSES:
            return existing, "unchanged"
        if origin == "import" and existing.origin != "import" and existing.status == "approved":
            return existing, "kept"  # R-TM-05: imports never overwrite reviewed work
        existing.target_tagged = target_tagged
        existing.target_plain = tagged_plain(target_tagged)
        existing.origin = origin
        existing.status = status
        existing.job_id = job_id
        existing.content_type = content_type
        if rights_confirmed_by:
            existing.rights_confirmed_by = rights_confirmed_by
        existing.updated_at = datetime.now(UTC)
        return existing, "updated"
    plain = tagged_plain(source_tagged)
    entry = TmEntry(
        org_id=org_id,
        source_lang=sl,
        target_lang=tl,
        content_type=content_type,
        source_tagged=source_tagged,
        target_tagged=target_tagged,
        source_plain=plain,
        target_plain=tagged_plain(target_tagged),
        source_hash=shash,
        context_hash=context_hash,
        embedding=embedding if embedding is not None else embed([plain])[0],
        status=status,
        origin=origin,
        rights_confirmed_by=rights_confirmed_by,
        job_id=job_id,
    )
    session.add(entry)
    return entry, "inserted"


def store(
    session: Session,
    org_id: str,
    source_lang: str,
    target_lang: str,
    source_tagged: str,
    target_tagged: str,
    *,
    content_type: str = "general",
    context_hash: str | None = None,
    origin: str = "review",
    job_id: str | None = None,
) -> TmEntry:
    """Upsert an approved translation (R-TM-05). Flushes, does not commit."""
    if not source_tagged.strip() or not target_tagged.strip():
        raise ValueError("source and target must be non-empty")
    entry, _ = _upsert(
        session,
        org_id,
        source_lang,
        target_lang,
        source_tagged,
        target_tagged,
        content_type=content_type,
        context_hash=context_hash,
        origin=origin,
        job_id=job_id,
        rights_confirmed_by=None,
        embedding=None,
    )
    session.flush()
    return entry


# ============================================================== TMX


def _secure_parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=True, huge_tree=True)


def _local(el: Any) -> str:
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


class _IdMap:
    """Assigns ⟦n⟧ ids per translation unit so source and target codes line up.

    TMX pairs bpt/ept by `i` and links codes across languages by `x`; codes without
    `x` are matched by order of appearance within their seg.
    """

    def __init__(self) -> None:
        self.ids: dict[tuple[str, str], str] = {}

    def get(self, key: tuple[str, str]) -> str:
        if key not in self.ids:
            self.ids[key] = str(len(self.ids) + 1)
        return self.ids[key]


def _seg_to_tagged(seg: Any, idmap: _IdMap) -> str:
    out: list[str] = []
    counters: Counter[str] = Counter()

    def walk(el: Any) -> None:
        if el.text:
            out.append(_escape(el.text))
        for child in el:
            name = _local(child)
            if name == "bpt":
                out.append(f"{LB}{idmap.get(('p', child.get('i') or child.get('x') or '?'))}{RB}")
            elif name == "ept":
                out.append(f"{LB}/{idmap.get(('p', child.get('i') or '?'))}{RB}")
            elif name in ("ph", "ut"):
                counters["ph"] += 1
                x = child.get("x")
                key = ("ph", x) if x else ("ph#", str(counters["ph"]))
                out.append(f"{LB}{idmap.get(key)}/{RB}")
            elif name == "it":
                counters["it"] += 1
                x = child.get("x")
                cid = idmap.get(("it", x) if x else ("it#", str(counters["it"])))
                out.append(f"{LB}/{cid}{RB}" if child.get("pos") == "end" else f"{LB}{cid}{RB}")
            elif name == "hi":
                counters["hi"] += 1
                x = child.get("x")
                cid = idmap.get(("hi", x) if x else ("hi#", str(counters["hi"])))
                out.append(f"{LB}{cid}{RB}")
                walk(child)
                out.append(f"{LB}/{cid}{RB}")
            elif name != "sub":
                walk(child)  # unknown element: keep its text
            if child.tail:
                out.append(_escape(child.tail))

    walk(seg)
    return "".join(out)


def import_tmx(
    session: Session,
    org_id: str,
    data: bytes,
    rights_confirmed_by: str,
    *,
    content_type: str = "general",
    source_lang: str | None = None,
) -> dict:
    """Import a TMX 1.4b file into the org's TM (R-TM-01: rights must be confirmed).

    The source language is the header srclang (or `source_lang` when srclang is
    "*all*"); every other tuv in a tu becomes one entry. Inline bpt/ept/ph/it/hi
    become ⟦n⟧ codes. Returns {imported, skipped, errors}.
    """
    if not (rights_confirmed_by or "").strip():
        raise ValueError("rights_confirmed_by is required: we only learn from TM the client owns (R-TM-01)")
    try:
        root = etree.fromstring(data, _secure_parser())
    except etree.XMLSyntaxError as e:
        return {"imported": 0, "skipped": 0, "errors": [f"invalid XML: {e}"]}
    header = next((c for c in root if _local(c) == "header"), None)
    srclang = (header.get("srclang") if header is not None else None) or source_lang or ""
    if srclang.lower() == "*all*":
        srclang = source_lang or ""

    pending: list[dict[str, Any]] = []
    errors: list[str] = []
    skipped = 0
    for n, tu in enumerate((el for el in root.iter() if _local(el) == "tu"), start=1):
        tuvs = []
        chash = None
        for c in tu:
            name = _local(c)
            if name == "prop" and c.get("type") == "x-context":
                chash = (c.text or "").strip() or None
            elif name == "tuv":
                lang = c.get(_XML_LANG) or c.get("lang") or ""
                seg = next((s for s in c if _local(s) == "seg"), None)
                if seg is not None and lang:
                    tuvs.append((lang, seg))
        if len(tuvs) < 2:
            skipped += 1
            continue
        src_idx = next((i for i, (lg, _) in enumerate(tuvs) if srclang and _compatible(lg, srclang)), None)
        if src_idx is None:
            if srclang:
                errors.append(f"tu {n}: no tuv in source language {srclang}")
                continue
            src_idx = 0
        idmap = _IdMap()
        src_lang, src_seg = tuvs[src_idx]
        src_tagged = _seg_to_tagged(src_seg, idmap)
        if not tagged_plain(src_tagged).strip():
            skipped += 1
            continue
        for i, (lang, seg) in enumerate(tuvs):
            if i == src_idx:
                continue
            tgt_tagged = _seg_to_tagged(seg, idmap)
            if not tagged_plain(tgt_tagged).strip():
                skipped += 1
                continue
            pending.append({"sl": src_lang, "tl": lang, "src": src_tagged, "tgt": tgt_tagged, "ctx": chash})

    imported = 0
    for start in range(0, len(pending), 256):
        chunk = pending[start : start + 256]
        vectors = embed([tagged_plain(p["src"]) for p in chunk])
        for p, vec in zip(chunk, vectors, strict=True):
            _, action = _upsert(
                session,
                org_id,
                p["sl"],
                p["tl"],
                p["src"],
                p["tgt"],
                content_type=content_type,
                context_hash=p["ctx"],
                origin="import",
                job_id=None,
                rights_confirmed_by=rights_confirmed_by.strip(),
                embedding=vec,
            )
            if action in ("inserted", "updated"):
                imported += 1
            else:
                skipped += 1
        session.flush()  # later chunks must see earlier rows for the upsert
    return {"imported": imported, "skipped": skipped, "errors": errors}


def _tagged_to_seg(parent: Any, tagged: str) -> None:
    """Write tagged text into a TMX <seg>: paired codes -> bpt/ept, standalone -> ph,
    a half pair without its partner in this segment -> it."""
    pieces = _pieces(tagged)
    opens = {v[0] for k, v in pieces if k == "code" and v[1] == "open"}
    closes = {v[0] for k, v in pieces if k == "code" and v[1] == "close"}
    paired = opens & closes
    num: dict[str, str] = {}

    def i_of(cid: str) -> str:
        if cid not in num:
            num[cid] = cid if cid.isdigit() else str(len(num) + 1)
        return num[cid]

    last: Any = None

    def add_text(text: str) -> None:
        if last is None:
            parent.text = (parent.text or "") + text
        else:
            last.tail = (last.tail or "") + text

    for kind, value in pieces:
        if kind == "text":
            add_text(value)
            continue
        cid, ckind = value
        if ckind == "standalone":
            last = etree.SubElement(parent, "ph", x=i_of(cid))
        elif cid in paired:
            last = etree.SubElement(parent, "bpt" if ckind == "open" else "ept", i=i_of(cid))
            if ckind == "open":
                last.set("x", i_of(cid))
        else:
            last = etree.SubElement(parent, "it", pos="begin" if ckind == "open" else "end", x=i_of(cid))


def export_tmx(session: Session, org_id: str, source_lang: str, target_lang: str) -> bytes:
    """Export servable entries for a pair as TMX 1.4b (context hash kept as x-context prop)."""
    stmt = (
        select(TmEntry)
        .where(
            TmEntry.org_id == org_id,
            TmEntry.status.in_(SERVABLE_STATUSES),
            _lang_clause(TmEntry.source_lang, source_lang),
            _lang_clause(TmEntry.target_lang, target_lang),
        )
        .order_by(TmEntry.created_at, TmEntry.id)
    )
    root = etree.Element("tmx", version="1.4")
    etree.SubElement(
        root,
        "header",
        creationtool="Arbiter",
        creationtoolversion="1",
        segtype="sentence",
        adminlang="en",
        srclang=norm_lang(source_lang),
        datatype="plaintext",
        **{"o-tmf": "arbiter"},
    )
    body = etree.SubElement(root, "body")
    for e in session.execute(stmt).scalars():
        if not (_compatible(e.source_lang, source_lang) and _compatible(e.target_lang, target_lang)):
            continue
        tu = etree.SubElement(body, "tu", tuid=e.id)
        if e.updated_at:
            tu.set("changedate", e.updated_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ"))
        if e.context_hash:
            etree.SubElement(tu, "prop", type="x-context").text = e.context_hash
        for lang, tagged in ((e.source_lang, e.source_tagged), (e.target_lang, e.target_tagged)):
            tuv = etree.SubElement(tu, "tuv")
            tuv.set(_XML_LANG, lang)
            _tagged_to_seg(etree.SubElement(tuv, "seg"), tagged)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
