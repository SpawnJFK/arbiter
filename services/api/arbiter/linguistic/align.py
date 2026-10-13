"""Sentence alignment of a source document and its translation (TM alignment, auditor pairs).

Two passes in one dynamic program:

1. Gale-Church (1993): the length of a translation is roughly proportional to the length
   of its source. For a candidate bead (1-1, 1-0, 0-1, 2-1, 1-2, 2-2 sentences) the cost is
   -log(prior(bead) * P(delta)), with delta = (l2 - l1*c) / sqrt(l1 * s2), c = 1, s2 = 6.8,
   and P(delta) = 2 * (1 - Phi(|delta|)). Lengths are in characters of plain text.
2. Embedding refinement: each bead also pays for low semantic similarity of its two sides
   (cosine of the averaged sentence embeddings from linguistic.embeddings). With a real
   multilingual embedding provider this fixes beads where lengths alone are ambiguous; with
   the mock provider it still rewards shared numbers, names and URLs.

The search runs inside a diagonal band, so documents of thousands of sentences stay cheap.
Each bead gets a confidence in [0, 1] for the review grid: a weighted mix of the length
probability and the similarity, 0 for 1-0 / 0-1 beads (nothing to store).
"""

from __future__ import annotations

import math
import operator
from dataclasses import dataclass, field

from arbiter.linguistic.embeddings import embed

C = 1.0
S2 = 6.8
# Gale-Church priors: 1-1 0.89, 1-0 + 0-1 0.0099, 2-1 + 1-2 0.089, 2-2 0.011.
PRIORS: dict[tuple[int, int], float] = {
    (1, 1): 0.89,
    (1, 0): 0.0099 / 2,
    (0, 1): 0.0099 / 2,
    (2, 1): 0.089 / 2,
    (1, 2): 0.089 / 2,
    (2, 2): 0.011,
}
SIM_WEIGHT = 2.0  # cost units per unit of (1 - cosine)
BAND_MIN = 12
FOLD = 4  # embeddings are folded 256 -> 64 dims for the DP: same neighbourhoods, 4x cheaper
MAX_EMBED_CELLS = 2_000_000  # n*m above this: lengths only (pure Python stays fast)


@dataclass
class Bead:
    src: list[int]
    tgt: list[int]
    confidence: float
    similarity: float = 0.0
    length_p: float = 0.0
    extra: dict[str, float] = field(default_factory=dict)


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def length_probability(l1: int, l2: int) -> float:
    if l1 == 0 and l2 == 0:
        return 1.0
    mean = (l1 + l2 / C) / 2.0
    delta = (l2 - l1 * C) / math.sqrt(max(mean, 1.0) * S2)
    return max(1e-12, 2.0 * (1.0 - _phi(abs(delta))))


def _unit(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _fold(vec: list[float]) -> list[float]:
    return _unit([sum(vec[k : k + FOLD]) for k in range(0, len(vec), FOLD)])


def _means(vectors: list[list[float]]) -> tuple[list[list[float]], list[list[float]]]:
    """Folded single-sentence vectors and folded means of each adjacent pair."""
    singles = [_fold(v) for v in vectors]
    pairs = [_unit(list(map(operator.add, a, b))) for a, b in zip(singles, singles[1:], strict=False)]
    return singles, pairs


def _cos(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    return max(-1.0, min(1.0, sum(map(operator.mul, a, b))))


def align(source: list[str], target: list[str], *, use_embeddings: bool = True) -> list[Bead]:
    """Align two lists of plain sentences. Returns beads in document order."""
    n, m = len(source), len(target)
    if n == 0 or m == 0:
        return [Bead([i], [], 0.0) for i in range(n)] + [Bead([], [j], 0.0) for j in range(m)]
    lens_s = [len(s) for s in source]
    lens_t = [len(t) for t in target]
    use_embeddings = use_embeddings and n * m <= MAX_EMBED_CELLS
    one_s, two_s = _means(embed(source)) if use_embeddings else ([], [])
    one_t, two_t = _means(embed(target)) if use_embeddings else ([], [])

    def sim_of(i0: int, di: int, j0: int, dj: int) -> float:
        a = one_s[i0] if di == 1 else two_s[i0]
        b = one_t[j0] if dj == 1 else two_t[j0]
        return _cos(a, b)

    band = max(BAND_MIN, int(0.1 * max(n, m)) + abs(n - m))

    inf = float("inf")
    cost = [[inf] * (m + 1) for _ in range(n + 1)]
    back: list[list[tuple[int, int] | None]] = [[None] * (m + 1) for _ in range(n + 1)]
    cost[0][0] = 0.0

    def bead_cost(i: int, j: int, di: int, dj: int) -> float:
        l1 = sum(lens_s[i - di : i])
        l2 = sum(lens_t[j - dj : j])
        c = -math.log(PRIORS[(di, dj)] * length_probability(l1, l2))
        if use_embeddings and di and dj:
            c += SIM_WEIGHT * (1.0 - sim_of(i - di, di, j - dj, dj))
        return c

    for i in range(n + 1):
        centre = i * m / n
        lo = max(0, int(centre) - band)
        hi = min(m, int(centre) + band)
        for j in range(lo, hi + 1):
            if i == 0 and j == 0:
                continue
            best, arg = inf, None
            for di, dj in PRIORS:
                if di > i or dj > j:
                    continue
                prev = cost[i - di][j - dj]
                if prev == inf:
                    continue
                c = prev + bead_cost(i, j, di, dj)
                if c < best:
                    best, arg = c, (di, dj)
            cost[i][j] = best
            back[i][j] = arg

    if back[n][m] is None:  # outside the band (very uneven documents): fall back to 1-1 order
        k = min(n, m)
        beads = [Bead([i], [i], 0.3) for i in range(k)]
        beads += [Bead([i], [], 0.0) for i in range(k, n)] + [Bead([], [j], 0.0) for j in range(k, m)]
        return beads

    path: list[tuple[int, int, int, int]] = []
    i, j = n, m
    while i > 0 or j > 0:
        step = back[i][j]
        assert step is not None
        di, dj = step
        path.append((i - di, j - dj, di, dj))
        i, j = i - di, j - dj
    path.reverse()

    beads: list[Bead] = []
    for i0, j0, di, dj in path:
        src = list(range(i0, i0 + di))
        tgt = list(range(j0, j0 + dj))
        if not di or not dj:
            beads.append(Bead(src, tgt, 0.0))
            continue
        lp = length_probability(sum(lens_s[i0 : i0 + di]), sum(lens_t[j0 : j0 + dj]))
        sim = sim_of(i0, di, j0, dj) if use_embeddings else 0.0
        conf = 0.7 * lp + 0.3 * max(0.0, sim)
        if (di, dj) != (1, 1):
            conf *= 0.85
        beads.append(Bead(src, tgt, round(min(1.0, conf), 3), round(sim, 3), round(lp, 3)))
    return beads
