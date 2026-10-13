"""Sentence alignment: Gale-Church lengths refined by embedding similarity."""

from __future__ import annotations

from arbiter.linguistic.align import align, length_probability


def test_one_to_one_in_order():
    src = ["The contract is signed today.", "We pay 300 EUR per month.", "Thanks."]
    tgt = ["Ugovor je potpisan danas.", "Placamo 300 EUR mesecno.", "Hvala."]
    beads = align(src, tgt)
    assert [(b.src, b.tgt) for b in beads] == [([0], [0]), ([1], [1]), ([2], [2])]
    assert all(0 < b.confidence <= 1 for b in beads)


def test_two_to_one_when_the_translation_joins_sentences():
    src = ["Open the menu.", "Then click Save.", "The file is stored in your account folder for 30 days."]
    tgt = ["Otvorite meni i kliknite Sacuvaj.", "Datoteka se cuva u folderu vaseg naloga 30 dana."]
    beads = align(src, tgt)
    assert [(b.src, b.tgt) for b in beads] == [([0, 1], [0]), ([2], [1])]


def test_every_sentence_is_covered_exactly_once_on_uneven_documents():
    src = [f"Sentence number {i} talks about item {i} in some detail." for i in range(40)]
    tgt = [f"Recenica broj {i} govori o stavci {i}." for i in range(0, 40, 2)]
    beads = align(src, tgt)
    assert sorted(i for b in beads for i in b.src) == list(range(40))
    assert sorted(j for b in beads for j in b.tgt) == list(range(20))
    # document order is kept on both sides
    flat_t = [j for b in beads for j in b.tgt]
    assert flat_t == sorted(flat_t)
    assert all(b.confidence == 0.0 for b in beads if not b.src or not b.tgt)


def test_empty_sides_and_length_probability():
    assert [(b.src, b.tgt) for b in align(["a", "b"], [])] == [([0], []), ([1], [])]
    assert align([], []) == []
    assert length_probability(100, 100) > length_probability(100, 160) > length_probability(100, 400)
