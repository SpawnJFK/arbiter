"""MQM scoring.

Formula (MQM-Core scoring model, linear calibration, max score 100):

    APT  = absolute penalty total = sum of severity weights of the errors
           weights: neutral 0, minor 1, major 5, critical 25 (contracts.SEVERITY_WEIGHT)
    EWC  = evaluation word count = words in the SOURCE segment (at least 1)
    score = 100 - APT * 100 / EWC, clamped to [0, 100]

i.e. the penalty is expressed per 100 words. Examples for a 20-word segment:
    no errors     -> 100
    one minor     -> 100 - 1*100/20  = 95
    one major     -> 100 - 5*100/20  = 75
    two minor     -> 90
    one critical  -> 100 - 25*100/20 = -25 -> 0

Why per segment and per 100 words: the routing threshold (default 78) is applied per
segment, so the score must react to one major error in a normal sentence (75 < 78 sends
it on) but must not punish a long paragraph with one minor slip below the line. Why the
source word count: it does not change when the target is edited, so before and after
scores of the same segment are comparable.

Word count: whitespace-delimited words; for scripts written without spaces (Chinese,
Japanese, Thai) every two characters count as one word, the usual industry approximation.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable

from arbiter.contracts import SEVERITY_WEIGHT, MqmError

_WORD_RE = re.compile(r"\w+", re.U)
_NO_SPACE_LANGS = ("zh", "ja", "th", "lo", "km", "my")
_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿฀-໿ក-៿က-႟]")


def evaluation_word_count(text: str, lang: str = "") -> int:
    if lang.lower().startswith(_NO_SPACE_LANGS):
        chars = len(_CJK_RE.findall(text))
        latin = len(_WORD_RE.findall(_CJK_RE.sub(" ", text)))
        return max(1, math.ceil(chars / 2) + latin)
    return max(1, len(_WORD_RE.findall(text)))


def penalty_total(errors: Iterable[MqmError]) -> int:
    return sum(SEVERITY_WEIGHT.get(e.severity, 0) for e in errors)


def mqm_score(errors: Iterable[MqmError], word_count: int) -> float:
    """100 - APT*100/EWC clamped to [0, 100], rounded to 2 decimals."""
    apt = penalty_total(errors)
    score = 100.0 - apt * 100.0 / max(word_count, 1)
    return round(min(100.0, max(0.0, score)), 2)
