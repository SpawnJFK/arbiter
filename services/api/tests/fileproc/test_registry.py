from __future__ import annotations

import pytest
from fileproc_fixtures import HTML, make_docx

from arbiter.fileproc import registry
from arbiter.fileproc.base import FormatError
from arbiter.fileproc.docx import DocxHandler
from arbiter.fileproc.registry import SUPPORTED_EXTENSIONS, detect_and_extract, get_handler


def test_lookup_is_case_insensitive() -> None:
    assert isinstance(get_handler("Report.DOCX"), DocxHandler)
    assert get_handler("dir.v2/strings.Json").name == "json"
    assert get_handler("messages.pot").name == "po"
    assert get_handler("page.htm").name == "html"
    for ext in ("docx", "xlsx", "pptx", "html", "md", "json", "po", "txt", "csv", "xlf", "xliff"):
        assert ext in SUPPORTED_EXTENSIONS


def test_pdf_refused() -> None:
    with pytest.raises(FormatError) as e:
        get_handler("contract.pdf")
    assert str(e.value) == registry.PDF_MESSAGE
    assert "not supported because the result would not be reliable" in str(e.value)


@pytest.mark.parametrize("name", ["old.doc", "old.XLS", "deck.ppt", "letter.rtf"])
def test_legacy_refused(name: str) -> None:
    with pytest.raises(FormatError, match="Legacy Office formats are not supported"):
        get_handler(name)


def test_unknown_lists_supported() -> None:
    with pytest.raises(FormatError) as e:
        get_handler("drawing.dwg")
    assert ".docx" in str(e.value) and ".xliff" in str(e.value) and ".dwg" in str(e.value)
    with pytest.raises(FormatError, match="without an extension"):
        get_handler("README")


@pytest.mark.parametrize("name,data", [("empty.txt", b""), ("blank.md", b"  \n\n"), ("nums.csv", b"1,2\n3,4\n"),
                                       ("only.json", b'{"a": 1, "b": "42"}')])
def test_no_translatable_text(name: str, data: bytes) -> None:
    with pytest.raises(FormatError, match="no translatable text"):
        detect_and_extract(name, data, "en")


def test_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "MAX_FILE_BYTES", 10)
    with pytest.raises(FormatError, match="1 GB"):
        detect_and_extract("a.txt", b"Hello world, long enough", "en")


def test_detect_and_extract() -> None:
    assert detect_and_extract("doc.docx", make_docx(), "en").segment_count > 5
    assert detect_and_extract("page.html", HTML.encode(), "en").format == "html"
    with pytest.raises(FormatError, match="damaged"):
        detect_and_extract("fake.docx", b"this is not a zip file", "en")
    with pytest.raises(FormatError):
        detect_and_extract("fake.xlsx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest", "en")
