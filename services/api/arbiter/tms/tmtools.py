"""TM tools: term extraction candidates, TM consistency QA, TM glossary QA.

Term extraction (statistical, no model call, R-GL-* terms are only added when a human
accepts a candidate):
1. Candidate n-grams (1 to 3 words) of the source texts that do not start or end with a
   stopword, are not numbers and do not cross punctuation.
2. Lemma grouping: n-grams are keyed by their Snowball stems, so "contract" and
   "contracts" are one candidate with both surface variants.
3. Nested candidates that never occur outside a longer one with the same frequency are
   dropped (a light C-value).
4. Target candidates from parallel text (job translations and the TM of the pair): target
   n-grams that co-occur with the source candidate, ranked by the Dice coefficient.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arbiter.linguistic import glossary as gl
from arbiter.linguistic.lemma import primary_lang, stem, tokenize
from arbiter.linguistic.tm import SERVABLE_STATUSES, _compatible, _lang_clause
from arbiter.models import Term, TmEntry


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


STOPWORDS: dict[str, frozenset[str]] = {
    "en": _words(
        "a an the and or but if then else of to in on at by for with from as is are was were be been being "
        "this that these those it its it's we you he she they them our your their his her my me us i not no "
        "do does did done can could will would shall should may might must have has had having there here "
        "which who whom whose what when where why how all any each every some such than too very so also "
        "into onto over under about after before between through during without within upon via per more "
        "most other only own same just both either neither nor up down out off again further once"
    ),
    "de": _words(
        "der die das den dem des ein eine einer eines einem einen und oder aber wenn dann von zu im in am an "
        "auf mit aus bei nach vor für über unter ist sind war waren sein wird werden hat haben nicht kein "
        "keine es er sie wir ihr ich du sich dieser diese dieses als auch so wie was wer wo nur noch schon "
        "zum zur durch um bis ohne gegen"
    ),
    "fr": _words(
        "le la les un une des du de d l et ou mais si à au aux en dans sur par pour avec sans sous est sont "
        "était être a ont avoir ne pas plus ce cet cette ces il elle ils elles nous vous je tu on qui que "
        "quoi dont où se sa son ses leur leurs comme aussi"
    ),
    "es": _words(
        "el la los las un una unos unas y o pero si de del al a en con sin por para sobre es son era ser "
        "está están ha han no más este esta estos estas ese esa lo le les se su sus que quien como también "
        "muy ya"
    ),
    "it": _words(
        "il lo la i gli le un uno una e o ma se di del della dei delle a al alla in con su per tra fra è "
        "sono era essere ha hanno non più questo questa che chi come anche si suo sua"
    ),
    "pt": _words(
        "o a os as um uma uns umas e ou mas se de do da dos das em no na nos nas por para com sem é são "
        "era ser está não mais este esta que quem como também seu sua"
    ),
    "nl": _words(
        "de het een en of maar als dan van te in op aan met voor door bij uit naar is zijn was waren wordt "
        "worden heeft hebben niet geen dit dat deze die er ook zo"
    ),
    "sr": _words(
        "i a ali ili da je su bio bila bilo biti u na o od do za sa s iz po pri kod kao što koji koja koje "
        "se ne ni to taj ta te ovaj ova ovo on ona ono mi vi oni"
    ),
}


def stopwords(lang: str) -> frozenset[str]:
    p = primary_lang(lang)
    if p in ("hr", "bs", "me", "sh", "cnr"):
        p = "sr"
    return STOPWORDS.get(p, frozenset())


def _ngrams(text: str, lang: str, max_n: int = 3) -> list[tuple[tuple[str, ...], str]]:
    """(stem key, surface) for every candidate n-gram in one text."""
    toks = tokenize(text)
    stop = stopwords(lang)
    out: list[tuple[tuple[str, ...], str]] = []
    for i in range(len(toks)):
        for n in range(1, max_n + 1):
            if i + n > len(toks):
                break
            window = toks[i : i + n]
            # do not cross punctuation: only whitespace or a hyphen between tokens
            if any(text[window[k][2] : window[k + 1][1]].strip() not in ("", "-") for k in range(n - 1)):
                break
            words = [w for w, _, _ in window]
            low = [w.lower() for w in words]
            if low[0] in stop or low[-1] in stop:
                continue
            if all(w.isdigit() for w in words) or max(len(w) for w in words) < 3:
                continue
            if any(any(ch.isdigit() for ch in w) for w in words) and n == 1:
                continue
            surface = text[window[0][1] : window[-1][2]]
            out.append((tuple(stem(w, lang) for w in words), surface))
    return out


def _contains(key: tuple[str, ...], hay: tuple[str, ...]) -> bool:
    n = len(key)
    return any(hay[i : i + n] == key for i in range(len(hay) - n + 1))


def extract_terms(
    sources: list[str],
    source_lang: str,
    *,
    target_lang: str = "",
    parallel: list[tuple[str, str]] | None = None,
    existing: set[str] | None = None,
    min_freq: int = 2,
    limit: int = 50,
) -> list[dict[str, Any]]:
    freq: Counter[tuple[str, ...]] = Counter()
    variants: dict[tuple[str, ...], Counter[str]] = defaultdict(Counter)
    for text in sources:
        for key, surface in _ngrams(text, source_lang):
            freq[key] += 1
            variants[key][surface] += 1
    known = {tuple(stem(w, source_lang) for w, _, _ in tokenize(t)) for t in (existing or set())}
    cands = [k for k, f in freq.items() if f >= min_freq and k not in known]
    # light C-value: drop a candidate fully explained by a longer one with the same frequency
    longer = sorted(cands, key=len, reverse=True)
    keep: list[tuple[str, ...]] = []
    for k in cands:
        if any(len(L) > len(k) and freq[L] == freq[k] and _contains(k, L) for L in longer):
            continue
        keep.append(k)
    keep.sort(
        key=lambda k: (-(freq[k] * (1 + 0.5 * (len(k) - 1))), -len(k), variants[k].most_common(1)[0][0])
    )
    keep = keep[:limit]

    targets_for: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    if parallel and target_lang:
        rows = []
        tgt_freq: Counter[tuple[str, ...]] = Counter()
        tgt_surface: dict[tuple[str, ...], Counter[str]] = defaultdict(Counter)
        for src, tgt in parallel:
            skey = tuple(stem(w, source_lang) for w, _, _ in tokenize(src))
            tgrams = {}
            for key, surface in _ngrams(tgt, target_lang):
                tgrams[key] = surface
            for key, surface in tgrams.items():
                tgt_freq[key] += 1
                tgt_surface[key][surface] += 1
            rows.append((skey, set(tgrams)))
        for k in keep:
            matching = [tg for skey, tg in rows if _contains(k, skey)]
            if not matching:
                continue
            co: Counter[tuple[str, ...]] = Counter()
            for tg in matching:
                co.update(tg)
            scored = []
            for tkey, c in co.items():
                dice = 2.0 * c / (len(matching) + tgt_freq[tkey])
                if dice >= 0.2:
                    scored.append((dice, len(tkey), tkey, c))
            scored.sort(key=lambda x: (-x[0], -x[1]))
            targets_for[k] = [
                {"term": tgt_surface[t].most_common(1)[0][0], "score": round(d, 3), "count": c}
                for d, _, t, c in scored[:3]
            ]
    return [
        {
            "source_term": variants[k].most_common(1)[0][0],
            "frequency": freq[k],
            "words": len(k),
            "variants": [v for v, _ in variants[k].most_common(5)],
            "target_candidates": targets_for.get(k, []),
        }
        for k in keep
    ]


def document_sentences(filename: str, data: bytes, lang: str) -> list[str]:
    """Every extracted segment of a document in any supported format, as tagged text."""
    from arbiter.fileproc.base import to_tagged
    from arbiter.fileproc.registry import detect_and_extract

    result = detect_and_extract(filename, data, lang)
    return [to_tagged(s.content) for u in result.units for s in u.segments]


def tm_parallel(
    session: Session, org_id: str, source_lang: str, target_lang: str, limit: int = 3000
) -> list[tuple[str, str]]:
    rows = session.execute(
        select(TmEntry.source_plain, TmEntry.target_plain, TmEntry.source_lang, TmEntry.target_lang)
        .where(
            TmEntry.org_id == org_id,
            TmEntry.status.in_(SERVABLE_STATUSES),
            _lang_clause(TmEntry.source_lang, source_lang),
            _lang_clause(TmEntry.target_lang, target_lang),
        )
        .order_by(TmEntry.updated_at.desc())
        .limit(limit)
    ).all()
    return [(s, t) for s, t, sl, tl in rows if _compatible(sl, source_lang) and _compatible(tl, target_lang)]


# --------------------------------------------------------------------------- TM QA


def inconsistencies(
    session: Session, org_id: str, source_lang: str, target_lang: str, limit: int = 100
) -> list[dict[str, Any]]:
    """Sources stored with more than one different translation (whitespace and case of the
    target ignored), most variants first."""
    base = [
        TmEntry.org_id == org_id,
        TmEntry.status.in_(SERVABLE_STATUSES),
        _lang_clause(TmEntry.source_lang, source_lang),
        _lang_clause(TmEntry.target_lang, target_lang),
    ]
    norm = func.lower(func.regexp_replace(func.trim(TmEntry.target_plain), r"\s+", " ", "g"))
    hashes = session.execute(
        select(TmEntry.source_hash, func.count(func.distinct(norm)).label("n"))
        .where(*base)
        .group_by(TmEntry.source_hash)
        .having(func.count(func.distinct(norm)) > 1)
        .order_by(func.count(func.distinct(norm)).desc(), TmEntry.source_hash)
        .limit(limit)
    ).all()
    out: list[dict[str, Any]] = []
    for h, _n in hashes:
        entries = list(
            session.execute(
                select(TmEntry).where(*base, TmEntry.source_hash == h).order_by(TmEntry.updated_at.desc())
            ).scalars()
        )
        groups: dict[str, dict[str, Any]] = {}
        for e in entries:
            key = " ".join(e.target_plain.split()).lower()
            g = groups.setdefault(
                key,
                {"target_tagged": e.target_tagged, "entry_ids": [], "origins": [], "updated_at": None},
            )
            g["entry_ids"].append(e.id)
            if e.origin not in g["origins"]:
                g["origins"].append(e.origin)
            if g["updated_at"] is None and e.updated_at:
                g["updated_at"] = e.updated_at.isoformat()
        out.append(
            {
                "source_tagged": entries[0].source_tagged,
                "source_lang": entries[0].source_lang,
                "target_lang": entries[0].target_lang,
                "variants": list(groups.values()),
            }
        )
    return out


def glossary_violations(
    session: Session, org_id: str, glossary_id: str, source_lang: str, target_lang: str, limit: int = 2000
) -> list[dict[str, Any]]:
    """TM entries whose target breaks a current term of the glossary (mandatory missing,
    forbidden used, do-not-translate changed)."""
    terms = list(
        session.execute(
            select(Term).where(
                Term.glossary_id == glossary_id,
                Term.valid_to.is_(None),
                _lang_clause(Term.source_lang, source_lang),
                _lang_clause(Term.target_lang, target_lang),
            )
        ).scalars()
    )
    if not terms:
        return []
    out: list[dict[str, Any]] = []
    entries = session.execute(
        select(TmEntry)
        .where(
            TmEntry.org_id == org_id,
            TmEntry.status.in_(SERVABLE_STATUSES),
            _lang_clause(TmEntry.source_lang, source_lang),
            _lang_clause(TmEntry.target_lang, target_lang),
        )
        .order_by(TmEntry.updated_at.desc())
        .limit(limit)
    ).scalars()
    for e in entries:
        hits = gl.find_source_terms(e.source_plain, terms, source_lang)
        if not hits:
            continue
        bad = [v for v in gl.check_target(e.target_plain, hits, target_lang) if v.severity == "error"]
        if bad:
            out.append(
                {
                    "entry_id": e.id,
                    "source_tagged": e.source_tagged,
                    "target_tagged": e.target_tagged,
                    "violations": [{"code": v.code, "term_id": v.term_id, "message": v.message} for v in bad],
                }
            )
    return out
