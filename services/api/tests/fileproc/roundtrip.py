"""Round-trip assertions shared by the format tests."""

from __future__ import annotations

from fileproc_fixtures import code_kinds, joined, plain, pseudo_targets, tagged

from arbiter.fileproc.base import ExtractionResult, FormatHandler, join_unit, source_targets


def identity(handler: FormatHandler, data: bytes, lang: str = "en") -> tuple[bytes, ExtractionResult]:
    """extract -> merge(source targets) -> extract: units must be unchanged."""
    first = handler.extract(data, lang)
    assert first.segment_count > 0
    merged = handler.merge(data, source_targets(first), lang)
    second = handler.extract(merged, lang)
    assert tagged(second) == tagged(first)
    return merged, first


def translation(
    handler: FormatHandler,
    data: bytes,
    lang: str = "en",
    target_lang: str = "de",
    left: str = "[[",
    right: str = "]]",
) -> tuple[bytes, ExtractionResult, ExtractionResult]:
    """Pseudo-translate every segment; the result must carry the new text and every code.

    Only for formats where the translation replaces the source text. Bilingual formats
    (PO, XLIFF) keep the source and have their own checks.
    """
    first = handler.extract(data, lang)
    targets = pseudo_targets(first, left, right)
    merged = handler.merge(data, targets, target_lang)
    second = handler.extract(merged, lang)
    by_id = {u.unit_id: u for u in second.units}
    for unit in first.units:
        assert unit.unit_id in by_id, unit.unit_id
        expected = join_unit(targets[unit.unit_id], unit.segments, unit.leading_ws)
        got = joined(by_id[unit.unit_id])
        assert plain(got) == plain(expected), unit.unit_id
        assert left in plain(got), unit.unit_id
        assert code_kinds(got) == code_kinds(expected), unit.unit_id
    return merged, first, second
