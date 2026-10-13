from __future__ import annotations

import io
import zipfile

import pytest
from extra_fixtures import STORY_MAIN, TRACKED_STORY, make_idml
from fileproc_fixtures import joined, plain, tagged
from lxml import etree
from roundtrip import identity, translation

from arbiter.fileproc.base import FormatError, InlineCode, source_targets
from arbiter.fileproc.idml import CHANGES_MESSAGE, IdmlHandler
from arbiter.fileproc.registry import detect_and_extract


def _parts(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {n: z.read(n) for n in z.namelist()}


def _story(data: bytes, name: str = "Stories/Story_u100.xml") -> etree._Element:
    return etree.fromstring(_parts(data)[name])


def test_idml_extraction() -> None:
    result = IdmlHandler().extract(make_idml(), "en")
    units = {uid: (segs, ctx) for uid, segs, ctx in tagged(result)}
    p = "Stories/Story_u100.xml"
    assert units[f"{p}#1"] == (["Kettle Guide"], "body, style Heading 1")
    # Three runs, the bold one becomes a pair; the paragraph is segmented.
    assert units[f"{p}#2"][0] == ["Fill the kettle with ⟦1⟧cold⟦/1⟧ water.", "Then press the switch."]
    # The paragraph starts inside the run that ended the previous one.
    assert units[f"{p}#3"][0] == ["Visit ⟦1⟧our site⟦/1⟧ for help.⟦2/⟧Tip inside."]
    assert units[f"{p}#4"][0] == ["See note⟦1/⟧⟦2/⟧ and the ⟦3⟧safety⟦/3⟧ rules."]
    assert units[f"{p}#5"] == (["⟦1/⟧ Tested in a fictional lab."], "footnote, style Footnote")
    assert units[f"{p}#7"] == (["Capacity"], "table")
    assert units[f"{p}#8"] == (["1.7 litres"], "table")
    assert units["Stories/Story_u200.xml#1"][0] == ["⟦1/⟧Side panel text."]
    texts = " ".join(plain(joined(u)) for u in result.units)
    assert "Editor: check wording" not in texts  # editorial notes are not translated
    assert "2024" not in texts  # numbers only
    displays = {
        c.display for u in result.units for s in u.segments for c in s.content if isinstance(c, InlineCode)
    }
    assert {"bold", "link", "special character", "note", "footnote", "style:Emphasis", "anchor"} <= displays


def test_idml_identity() -> None:
    data = make_idml()
    merged, _ = identity(IdmlHandler(), data)
    assert merged == data


def test_idml_translation() -> None:
    data = make_idml()
    merged, _, _ = translation(IdmlHandler(), data)
    before, after = _parts(data), _parts(merged)
    with zipfile.ZipFile(io.BytesIO(merged)) as z:
        first = z.infolist()[0]
        assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
    for name in ("mimetype", "designmap.xml", "META-INF/container.xml"):
        assert before[name] == after[name]
    story = after["Stories/Story_u100.xml"].decode()
    assert story.startswith('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>')
    assert (
        '<HyperlinkTextSource Self="hts1" Name="Site" Hidden="false"><Content>[[OUR SITE]]</Content>' in story
    )
    assert "<Content>Editor: check wording</Content>" in story
    assert "<?ACE 7?>[[TIP INSIDE.]]" in story and "<?ACE 4?>[[ TESTED IN A FICTIONAL LAB.]]" in story
    assert "[[CAPACITY]]" in story and "<Content>2024</Content>" in story
    assert story.count("<Br/>") == STORY_MAIN.count("<Br/>")


def test_idml_reordered_codes_rebuild_runs() -> None:
    data = make_idml()
    h = IdmlHandler()
    result = h.extract(data, "en")
    targets = source_targets(result)
    uid = "Stories/Story_u100.xml#4"
    unit = next(u for u in result.units if u.unit_id == uid)
    seg = unit.segments[0].content
    note, foot, o3, c3 = [c for c in seg if isinstance(c, InlineCode)]
    # The target moves the emphasis to the front and the note and footnote to the end.
    targets[uid] = [[o3, "Sicherheit", c3, "sregeln beachten", note, foot, "."]]
    out = h.merge(data, targets, "de")
    story = _story(out)
    assert len(story.findall(".//Note")) == 1 and len(story.findall(".//Footnote")) == 1
    again = {u.unit_id: u for u in h.extract(out, "de").units}
    assert [to for _, to, _ in tagged(type(result)("idml", "de", [again[uid]]))] == [
        ["⟦1⟧Sicherheit⟦/1⟧sregeln beachten⟦2/⟧⟦3/⟧."]
    ]
    # Neighbouring paragraphs and the footnote text are untouched.
    assert plain(joined(again["Stories/Story_u100.xml#3"])) == "Visit our site for help.Tip inside."
    assert plain(joined(again["Stories/Story_u100.xml#5"])) == " Tested in a fictional lab."
    runs = [
        r
        for r in story.iter("CharacterStyleRange")
        if r.get("AppliedCharacterStyle") == "CharacterStyle/Emphasis"
    ]
    assert any((r.findtext("Content") or "") == "Sicherheit" for r in runs)


def test_idml_rebuild_in_shared_run() -> None:
    """Paragraph 3 shares its run with paragraph 2 and dropping the link pair forces a rebuild."""
    data = make_idml()
    h = IdmlHandler()
    result = h.extract(data, "en")
    targets = source_targets(result)
    uid = "Stories/Story_u100.xml#3"
    unit = next(u for u in result.units if u.unit_id == uid)
    pi = [c for c in unit.segments[0].content if isinstance(c, InlineCode) and c.kind == "standalone"][0]
    targets[uid] = [["Besuchen Sie unsere Seite.", pi, "Tipp."]]
    out = h.merge(data, targets, "de")
    again = {u.unit_id: u for u in h.extract(out, "de").units}
    assert plain(joined(again[uid])) == "Besuchen Sie unsere Seite.Tipp."
    assert plain(joined(again["Stories/Story_u100.xml#2"])).startswith("Fill the kettle with cold water.")
    story = _story(out)
    assert story.find(".//HyperlinkTextSource") is None  # the translator removed the link pair
    assert story.find(".//Footnote") is not None


TAGGED_STORY = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<idPkg:Story xmlns:idPkg="http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging" DOMVersion="18.0">'
    '<Story Self="u400"><ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/$ID/NormalParagraphStyle">'
    '<CharacterStyleRange AppliedCharacterStyle="n"><Content>Tagged </Content></CharacterStyleRange>'
    '<XMLElement Self="x1" MarkupTag="XMLTag/product">'
    '<CharacterStyleRange AppliedCharacterStyle="n" FontStyle="Bold"><Content>kettle</Content></CharacterStyleRange>'
    "</XMLElement>"
    '<CharacterStyleRange AppliedCharacterStyle="n"><Content> text here.</Content></CharacterStyleRange>'
    "</ParagraphStyleRange></Story></idPkg:Story>\n"
)


def test_idml_tagged_structure() -> None:
    data = make_idml({"Stories/Story_u400.xml": TAGGED_STORY})
    h = IdmlHandler()
    result = h.extract(data, "en")
    assert tagged(result) == [("Stories/Story_u400.xml#1", ["Tagged ⟦1⟧kettle⟦/1⟧ text here."], "body")]
    assert identity(h, data)[0] == data
    out, _, _ = translation(h, data)
    story = _story(out, "Stories/Story_u400.xml")
    assert story.find(".//XMLElement").findtext(".//Content") == "[[KETTLE]]"  # text kept inside its tag
    # Same code order: text is redistributed even though the run sits inside a tag.
    o1, c1 = [c for c in result.units[0].segments[0].content if isinstance(c, InlineCode)]
    out = h.merge(data, {"Stories/Story_u400.xml#1": [["Text mit ", o1, "Kocher", c1, "."]]}, "de")
    assert _story(out, "Stories/Story_u400.xml").find(".//XMLElement").findtext(".//Content") == "Kocher"
    # Dropping the pair needs a rebuild across the tag, which cannot be stored: a clear refusal.
    with pytest.raises(FormatError, match="original order"):
        h.merge(data, {"Stories/Story_u400.xml#1": [["Text mit Kocher."]]}, "de")


def test_idml_tracked_changes_refused() -> None:
    data = make_idml({"Stories/Story_u300.xml": TRACKED_STORY})
    with pytest.raises(FormatError) as e:
        IdmlHandler().extract(data, "en")
    assert str(e.value) == CHANGES_MESSAGE


def test_idml_not_a_package() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/zip")
    with pytest.raises(FormatError, match="not a valid IDML"):
        IdmlHandler().extract(buf.getvalue(), "en")
    with pytest.raises(FormatError):
        detect_and_extract("brochure.idml", b"not a zip at all", "en")


def test_idml_registry() -> None:
    assert detect_and_extract("Brochure.IDML", make_idml(), "en").format == "idml"


def test_idml_unknown_unit_refused() -> None:
    with pytest.raises(FormatError, match="does not exist"):
        IdmlHandler().merge(make_idml(), {"Stories/Story_u100.xml#99": [["x"]]}, "de")
