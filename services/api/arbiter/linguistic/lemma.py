"""Tokenization, light lemmatization and script normalisation for term matching.

Glossary terms must be found in inflected text (R-GL-03): a mandatory "ugovor" is
satisfied by "ugovora" or "ugovorom", "Vertrag" by "Verträge". We use Snowball
stemmers rather than full lemmatizers: they are deterministic, fast, dependency free
and good enough to compare a term against a token. Languages without a Snowball
algorithm fall back to lowercase identity (exact word match), which is strict but
never invents a match.

Serbian is written in two scripts. stem() transliterates Cyrillic to Latin for the
sr/bs/me/sh family, so a Latin glossary term matches a Cyrillic target and vice
versa. DNT checks never go through this module: a Latin brand inside Cyrillic text
must stay Latin, so those comparisons are char-exact (R-GL-07).
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

import snowballstemmer  # type: ignore[import-untyped]

# ISO 639-1 primary subtag -> Snowball algorithm. Close relatives share a stemmer
# where the endings are near-identical (sk -> czech, hr/bs/me -> serbian).
_STEMMER_FOR: dict[str, str] = {
    "ar": "arabic",
    "hy": "armenian",
    "eu": "basque",
    "ca": "catalan",
    "cs": "czech",
    "sk": "czech",
    "da": "danish",
    "nl": "dutch",
    "en": "english",
    "eo": "esperanto",
    "et": "estonian",
    "fi": "finnish",
    "fr": "french",
    "de": "german",
    "el": "greek",
    "hi": "hindi",
    "hu": "hungarian",
    "id": "indonesian",
    "ga": "irish",
    "it": "italian",
    "lt": "lithuanian",
    "ne": "nepali",
    "no": "norwegian",
    "nb": "norwegian",
    "nn": "norwegian",
    "fa": "persian",
    "pl": "polish",
    "pt": "portuguese",
    "ro": "romanian",
    "ru": "russian",
    "sr": "serbian",
    "hr": "serbian",
    "bs": "serbian",
    "me": "serbian",
    "cnr": "serbian",
    "sh": "serbian",
    "st": "sesotho",
    "es": "spanish",
    "sv": "swedish",
    "ta": "tamil",
    "tr": "turkish",
    "yi": "yiddish",
}

# Languages written (also) in Serbian Cyrillic: fold to Latin before comparing.
_SERBIAN_SCRIPT_FAMILY = frozenset({"sr", "bs", "me", "cnr", "sh"})

# Agglutinative languages where Snowball leaves consonant-gradation variants
# (Finnish "sopimus" / "sopimuksen" -> "sopimus" / "sopimuks"). For these we also
# accept stems that differ only in their last couple of characters.
_LOOSE_STEM_LANGS = frozenset({"fi", "et", "hu", "tr"})

_CYR_TO_LAT: dict[str, str] = {
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Ђ": "Đ", "Е": "E", "Ж": "Ž",
    "З": "Z", "И": "I", "Ј": "J", "К": "K", "Л": "L", "Љ": "Lj", "М": "M", "Н": "N",
    "Њ": "Nj", "О": "O", "П": "P", "Р": "R", "С": "S", "Т": "T", "Ћ": "Ć", "У": "U",
    "Ф": "F", "Х": "H", "Ц": "C", "Ч": "Č", "Џ": "Dž", "Ш": "Š",
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ђ": "đ", "е": "e", "ж": "ž",
    "з": "z", "и": "i", "ј": "j", "к": "k", "л": "l", "љ": "lj", "м": "m", "н": "n",
    "њ": "nj", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "ћ": "ć", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "č", "џ": "dž", "ш": "š",
}  # fmt: skip
_CYR_TABLE = str.maketrans(_CYR_TO_LAT)

# A word: letters/digits (plus combining marks), optionally joined by apostrophes
# ("l'accord", "don't"). Hyphens split words, so "e-mail" is two tokens and a
# hyphenated glossary term matches as a two-token sequence.
_WORD_RE = re.compile(r"[\ẁ-ͯ]+(?:['’][\ẁ-ͯ]+)*")


def primary_lang(lang: str) -> str:
    """'sr-Latn-RS' / 'sr_latn' -> 'sr'. Matching is by primary subtag (R-GL-04)."""
    return (lang or "").strip().lower().replace("_", "-").split("-")[0]


def norm_lang(lang: str) -> str:
    """Canonical storage form: lowercase, hyphen separated ('sr-latn', 'pt-br')."""
    return (lang or "").strip().lower().replace("_", "-")


def has_stemmer(lang: str) -> bool:
    return primary_lang(lang) in _STEMMER_FOR


def is_loose(lang: str) -> bool:
    return primary_lang(lang) in _LOOSE_STEM_LANGS


def to_latin(text: str) -> str:
    """Serbian Cyrillic -> Gaj Latin. Non-Cyrillic characters pass through unchanged."""
    return text.translate(_CYR_TABLE)


@lru_cache(maxsize=64)
def _stemmer(algorithm: str) -> snowballstemmer.stemmer:
    return snowballstemmer.stemmer(algorithm)


@lru_cache(maxsize=200_000)
def stem(word: str, lang: str) -> str:
    """Case-folded stem of one word; lowercase identity when no stemmer exists."""
    p = primary_lang(lang)
    w = unicodedata.normalize("NFC", word).lower()
    if p in _SERBIAN_SCRIPT_FAMILY:
        w = to_latin(w)
    algo = _STEMMER_FOR.get(p)
    if algo is None:
        return w
    return _stemmer(algo).stemWord(w)


def tokenize(text: str) -> list[tuple[str, int, int]]:
    """Unicode word tokens with their [start, end) char offsets in `text`."""
    return [(m.group(0), m.start(), m.end()) for m in _WORD_RE.finditer(text)]


def stems_match(a: str, b: str, lang: str) -> bool:
    """True when two stems denote the same word form family.

    Exact equality everywhere; for agglutinative languages also a shared prefix that
    leaves at most two characters on either side (consonant gradation).
    """
    if a == b:
        return True
    if not is_loose(lang):
        return False
    n = min(len(a), len(b))
    cp = 0
    while cp < n and a[cp] == b[cp]:
        cp += 1
    return cp >= 4 and cp >= n - 1 and max(len(a), len(b)) - cp <= 2
