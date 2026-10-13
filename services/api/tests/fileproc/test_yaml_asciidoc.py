from __future__ import annotations

import io

import pytest
from extra_fixtures import ASCIIDOC, YAML_DOC, YAML_MULTI
from fileproc_fixtures import joined, plain, tagged
from roundtrip import identity, translation
from ruamel.yaml import YAML

from arbiter.fileproc.asciidoc import AsciidocHandler
from arbiter.fileproc.base import FormatError, source_targets
from arbiter.fileproc.registry import detect_and_extract
from arbiter.fileproc.yamlfmt import YamlHandler


def _load(text: str) -> object:
    return YAML(typ="safe", pure=True).load(io.StringIO(text))


# --------------------------------------------------------------------------- YAML


def test_yaml_extraction() -> None:
    result = YamlHandler().extract(YAML_DOC.encode(), "en")
    units = {uid: segs for uid, segs, _ in tagged(result)}
    assert units == {
        "/en/app/title": ["Kettle"],
        "/en/app/greeting": ["Hello, ⟦1/⟧!"],
        "/en/app/quoted": ["It's ready"],
        "/en/defaults/tip": ["Pour slowly"],  # anchored once; the merge key and alias are not units
        "/en/steps/0": ["Fill the kettle"],
        "/en/steps/1": ["Press: start"],
        "/en/literal": ["First line.\nSecond line."],
        "/en/folded": ["A folded paragraph on two lines."],
        "/en/flow/short": ["Boil now"],
        "/en/flow/long/0": ["Keep warm"],
        "/en/flow/long/1": ["Cool down"],
    }
    assert all(len(u.segments) == 1 for u in result.units)


def test_yaml_identity_and_translation() -> None:
    data = YAML_DOC.encode()
    assert identity(YamlHandler(), data)[0] == data
    out, _, _ = translation(YamlHandler(), data)
    text = out.decode()
    assert "# Rails style locale file\nen:\n" in text
    assert 'title: "[[KETTLE]]"   # product name' in text
    assert "quoted: '[[IT''S READY]]'" in text  # single-quoted stays single-quoted
    assert "  defaults: &defaults\n" in text and "<<: *defaults" in text
    assert "  literal: |\n    [[FIRST LINE.\n    SECOND LINE.]]\n" in text
    loaded = _load(text)
    assert isinstance(loaded, dict)
    en = loaded["en"]
    assert en["app"]["greeting"] == "[[HELLO, ]]%{name}[[!]]"
    assert en["app"]["count"] == 3 and en["app"]["enabled"] is True
    assert en["copy"]["tip"] == "[[POUR SLOWLY]]"  # merge key follows the translated anchor
    assert en["copy"]["other"]["tip"] == "[[POUR SLOWLY]]"
    assert en["folded"] == "[[A FOLDED PARAGRAPH ON TWO LINES.]]"
    assert en["flow"]["long"] == ["[[KEEP WARM]]", "[[COOL DOWN]]"]


def test_yaml_style_choice() -> None:
    data = b"a: Kettle\nb: Tea\nc: Coffee\nd: |\n  one\n\n  two\n"
    h = YamlHandler()
    result = h.extract(data, "en")
    targets = source_targets(result)
    targets["/a"] = [["Wasserkocher"]]  # safe as plain
    targets["/b"] = [["yes"]]  # would turn into a boolean
    targets["/c"] = [["Kaffee: stark"]]  # ": " needs quotes
    targets["/d"] = [["eins\n\nzwei"]]
    out = h.merge(data, targets, "de").decode()
    assert out == 'a: Wasserkocher\nb: "yes"\nc: "Kaffee: stark"\nd: |\n  eins\n\n  zwei\n'
    assert _load(out) == {"a": "Wasserkocher", "b": "yes", "c": "Kaffee: stark", "d": "eins\n\nzwei\n"}


def test_yaml_anchored_scalar_translated_once() -> None:
    data = b"tip: &t Pour slowly\nagain: *t\ntagged: !!str Boil now\n"
    h = YamlHandler()
    result = h.extract(data, "en")
    assert [(u.unit_id, plain(joined(u))) for u in result.units] == [
        ("/tip", "Pour slowly"),
        ("/tagged", "Boil now"),
    ]
    out = h.merge(data, {"/tip": [["Langsam giessen"]], "/tagged": [["Jetzt kochen"]]}, "de").decode()
    assert out == "tip: &t Langsam giessen\nagain: *t\ntagged: !!str Jetzt kochen\n"
    assert _load(out) == {"tip": "Langsam giessen", "again": "Langsam giessen", "tagged": "Jetzt kochen"}


def test_yaml_multi_document_and_errors() -> None:
    result = YamlHandler().extract(YAML_MULTI.encode(), "en")
    assert [u.unit_id for u in result.units] == ["doc1/title", "doc2/title"]
    translation(YamlHandler(), YAML_MULTI.encode())
    with pytest.raises(FormatError, match="YAML file could not be read"):
        detect_and_extract("bad.yml", b"a: [unclosed\nb: x\n", "en")


# --------------------------------------------------------------------------- AsciiDoc


def test_asciidoc_extraction() -> None:
    result = AsciidocHandler().extract(ASCIIDOC.encode(), "en")
    units = {uid: (segs, ctx) for uid, segs, ctx in tagged(result)}
    assert units["L1"] == (["Kettle User Guide"], "heading")
    assert units["L5"] == (["Getting ⟦1⟧started⟦/1⟧"], "heading")
    assert units["L7"][0] == [
        "Fill the kettle with ⟦1⟧cold⟦/1⟧ water.",
        "Then press the ⟦2/⟧ button.",
        "See ⟦3⟧the help page⟦/3⟧ for ⟦4/⟧ details.",
    ]
    assert units["L13"] == (["Safety first"], "block title")
    assert units["L14"] == (["Never open the lid while boiling."], "note")
    assert units["L16"] == (["First item with ⟦1⟧a cross reference⟦/1⟧"], "list item")
    assert units["L17"][0] == ["Second item⟦1/⟧continued here"]
    assert units["L20.t"] == (["Term one"], "term")
    assert units["L20"] == (["Definition of the term."], "definition")
    assert units["L29.c2"] == (["1.7 litres"], "table")
    assert units["L35"][0] == ["A quoted sentence."]
    texts = " ".join(plain(joined(u)) for u in result.units)
    for hidden in (
        "Example Author",
        "never translated",
        "not translated",
        "indented literal",
        "source,python",
    ):
        assert hidden not in texts


def test_asciidoc_identity_and_translation() -> None:
    data = ASCIIDOC.encode()
    assert identity(AsciidocHandler(), data)[0] == data
    out, _, _ = translation(AsciidocHandler(), data, left="‹‹", right="››")
    text = out.decode()
    assert "== ‹‹GETTING ››*‹‹STARTED››*" in text
    assert "‹‹THEN PRESS THE ››`start`‹‹ BUTTON.››" in text
    assert "link:https://example.com/help[‹‹THE HELP PAGE››]‹‹ FOR ››{product}" in text
    assert "* ‹‹SECOND ITEM›› +\n‹‹CONTINUED HERE››" in text
    assert '----\nprint("not translated")\n----' in text and ":author: Example Author" in text
    assert detect_and_extract("guide.adoc", data, "en").format == "asciidoc"
