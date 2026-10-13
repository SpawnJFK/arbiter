from __future__ import annotations

import pytest
from extra_fixtures import ASS, SRT, VTT
from fileproc_fixtures import tagged
from roundtrip import identity, translation

from arbiter.fileproc.base import FormatError, InlineCode, source_targets
from arbiter.fileproc.registry import detect_and_extract, get_handler
from arbiter.fileproc.subtitles import AssHandler, SrtHandler, VttHandler

# --------------------------------------------------------------------------- SRT


def test_srt_extraction() -> None:
    result = SrtHandler().extract(SRT.encode(), "en")
    assert tagged(result) == [
        ("cue1", ["Welcome to the ⟦1⟧kettle⟦/1⟧ tutorial."], "subtitle 00:00:01,000 --> 00:00:03,500"),
        (
            "cue2",
            ["⟦1/⟧Fill it with water,⟦2/⟧then press ⟦3⟧start⟦/3⟧."],
            "subtitle 00:00:04,000 --> 00:00:07,250",
        ),
        ("cue3", ["⟦1⟧Done!⟦/1⟧"], "subtitle 00:00:08,000 --> 00:00:09,000"),
    ]
    codes = {c.display for u in result.units for c in u.segments[0].content if isinstance(c, InlineCode)}
    assert {"line break", "position", "<i>", "<b>", "<font>"} <= codes
    assert all(len(u.segments) == 1 and u.max_length is None for u in result.units)


def test_srt_identity_and_translation() -> None:
    data = SRT.encode()
    merged, _ = identity(SrtHandler(), data)
    assert merged == data
    out, _, _ = translation(SrtHandler(), data)
    text = out.decode()
    assert (
        "00:00:04,000 --> 00:00:07,250 X1:10 X2:100 Y1:10 Y2:50\r\n{\\an8}[[FILL IT WITH WATER,]]\r\n" in text
    )
    assert "[[THEN PRESS ]]<b>[[START]]</b>[[.]]\r\n" in text
    assert text.endswith("4\r\n00:00:10,000 --> 00:00:11,000\r\n123\r\n")


def test_srt_max_chars_option_and_line_breaks() -> None:
    h = get_handler("movie.srt", {"max_chars_per_line": 42})
    result = h.extract(SRT.encode(), "en")
    cue2 = result.units[1]
    assert cue2.max_length == 84 and cue2.notes == ["At most 42 characters per line, 2 line(s)."]
    assert result.units[0].max_length == 42
    # A raw line break typed by a translator must not create a blank line (it would end the cue).
    targets = source_targets(result)
    targets["cue1"] = [["Willkommen\n\nzum Kurs."]]
    out = h.merge(SRT.encode(), targets, "de").decode()
    assert "Willkommen zum Kurs.\r\n\r\n2\r\n" in out


@pytest.mark.parametrize("options", [{"max_chars_per_line": 0}, {"max_chars_per_line": "42"}, {"lines": 2}])
def test_subtitle_options_validated(options: dict) -> None:
    with pytest.raises(FormatError):
        get_handler("movie.srt", options)


def test_srt_malformed() -> None:
    with pytest.raises(FormatError, match="timing line"):
        SrtHandler().extract(b"1\nnot a timing line\nHello\n", "en")


# --------------------------------------------------------------------------- WebVTT


def test_vtt_extraction() -> None:
    result = VttHandler().extract(VTT.encode(), "en")
    units = {uid: segs for uid, segs, _ in tagged(result)}
    assert units["cue1"] == ["⟦1⟧Welcome to the ⟦2⟧kettle⟦/2⟧ tutorial.⟦/1⟧"]
    assert units["cue2"] == ["⟦1/⟧Fill it with water & wait⟦2/⟧⟦3/⟧until it ⟦4⟧clicks⟦/4⟧."]
    assert units["cue3"] == ["Tom <3 tea"]
    displays = [c.display for c in result.units[0].segments[0].content if isinstance(c, InlineCode)]
    assert displays[0] == "speaker:Ana"
    assert result.units[1].segments[0].content[0].display == "speaker:Ben"  # unclosed voice: standalone
    texts = " ".join(str(u.segments[0].content) for u in result.units)
    assert "editors only" not in texts and "yellow" not in texts and "Kettle tutorial" not in texts


def test_vtt_identity_and_translation() -> None:
    data = VTT.encode()
    merged, _ = identity(VttHandler(), data)
    assert merged == data
    out, _, _ = translation(VttHandler(), data)
    text = out.decode()
    assert (
        "00:00:01.000 --> 00:00:03.500 align:start position:10%\n<v Ana>[[WELCOME TO THE ]]<c.highlight>"
        in text
    )
    assert "[[FILL IT WITH WATER &amp; WAIT]]\n<00:00:05.500>[[UNTIL IT ]]<i>[[CLICKS]]</i>[[.]]" in text
    assert "[[TOM &lt;3 TEA]]" in text
    assert "NOTE This note is for editors only." in text and "::cue { color: yellow; }" in text


def test_vtt_requires_header() -> None:
    with pytest.raises(FormatError, match="WEBVTT"):
        detect_and_extract("captions.vtt", b"00:00.000 --> 00:01.000\nHello there\n", "en")


# --------------------------------------------------------------------------- ASS / SSA


def test_ass_extraction() -> None:
    result = AssHandler().extract(ASS.encode(), "en")
    assert tagged(result) == [
        (
            "dlg1",
            ["Welcome to the ⟦1⟧kettle⟦/1⟧ tutorial."],
            "subtitle 0:00:01.00 --> 0:00:03.50, style Default, speaker Ana",
        ),
        (
            "dlg2",
            ["⟦1/⟧Fill it with water,⟦2/⟧then wait."],
            "subtitle 0:00:04.00 --> 0:00:07.00, style Default, speaker Ben",
        ),
        ("dlg3", ["Text, with a comma."], "subtitle 0:00:08.00 --> 0:00:09.00, style Default"),
    ]
    first = [c for c in result.units[0].segments[0].content if isinstance(c, InlineCode)]
    assert [(c.kind, c.display, c.original) for c in first] == [
        ("open", "italic", "{\\i1}"),
        ("close", "italic", "{\\i0}"),
    ]


def test_ass_identity_translation_and_limits() -> None:
    data = ASS.encode()
    merged, _ = identity(AssHandler(), data)
    assert merged == data
    out, _, _ = translation(AssHandler(), data)
    text = out.decode()
    assert (
        "Dialogue: 0,0:00:04.00,0:00:07.00,Default,Ben,0,0,0,,{\\pos(10,20)}[[FILL IT WITH WATER,]]\\N"
        in text
    )
    assert "Comment: 0,0:00:02.00,0:00:03.00,Default,,0,0,0,,Editor comment, not shown" in text
    assert "Style: Default,Arial,20,&H00FFFFFF,0,0" in text
    limited = AssHandler(max_chars_per_line=30).extract(data, "en")
    assert [u.max_length for u in limited.units] == [30, 60, 30]
    # Braces would start an override block in ASS, so translations cannot introduce them.
    targets = source_targets(limited)
    targets["dlg3"] = [["Text {wichtig}"]]
    assert "Text (wichtig)" in AssHandler().merge(data, targets, "de").decode()


def test_ass_needs_format_line() -> None:
    bad = "[Events]\nDialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,Hello\n"
    with pytest.raises(FormatError, match="Format line"):
        AssHandler().extract(bad.encode(), "en")
    assert get_handler("old.ssa").name == "ass"
