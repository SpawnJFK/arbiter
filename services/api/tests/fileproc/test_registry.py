from __future__ import annotations

import pytest
from fileproc_fixtures import HTML, make_docx
from roundtrip import identity, translation

from arbiter.fileproc import ocr, registry
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


@pytest.mark.parametrize(
    "name,data",
    [
        ("empty.txt", b""),
        ("blank.md", b"  \n\n"),
        ("nums.csv", b"1,2\n3,4\n"),
        ("only.json", b'{"a": 1, "b": "42"}'),
    ],
)
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


# --------------------------------------------------------------------------- added formats, scans and options


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Brochure.idml", "idml"),
        ("movie.srt", "srt"),
        ("movie.vtt", "vtt"),
        ("movie.ass", "ass"),
        ("movie.ssa", "ass"),
        ("data.xml", "xml"),
        ("topic.dita", "dita"),
        ("guide.ditamap", "dita"),
        ("app_en.arb", "arb"),
        ("Localizable.strings", "strings"),
        ("Localizable.stringsdict", "stringsdict"),
        ("messages.properties", "properties"),
        ("Resources.resx", "resx"),
        ("en.yml", "yaml"),
        ("en.yaml", "yaml"),
        ("table.tsv", "tsv"),
        ("guide.adoc", "asciidoc"),
    ],
)
def test_new_extensions(name: str, expected: str) -> None:
    assert get_handler(name).name == expected
    assert name.rsplit(".", 1)[1].lower() in SUPPORTED_EXTENSIONS


def test_tsv_does_not_sniff_commas() -> None:
    data = b"key\ttext\nhello\tHello, world; again\nbye\tGoodbye\n"
    result = detect_and_extract("strings.tsv", data, "en")
    assert ["Hello, world; again"] in [s.content for u in result.units for s in u.segments]
    assert identity(get_handler("strings.tsv"), data)[0] == data
    out, _, _ = translation(get_handler("strings.tsv"), data)
    assert b"[[HELLO, WORLD; AGAIN]]" in out and out.count(b"\t") == data.count(b"\t")


@pytest.mark.parametrize("name", ["scan.png", "photo.JPG", "page.tiff", "shot.webp"])
def test_images_refused_with_ocr_message(name: str) -> None:
    with pytest.raises(FormatError) as e:
        detect_and_extract(name, b"\x89PNG\r\n\x1a\nbinary", "en")
    assert str(e.value) == ocr.IMAGE_MESSAGE
    assert "upload the original source file" in str(e.value)
    assert name.rsplit(".", 1)[1].lower() not in SUPPORTED_EXTENSIONS


def test_scanned_pdf_has_its_own_message() -> None:
    scanned = b"%PDF-1.4\n1 0 obj << /Type /XObject /Subtype /Image /Width 10 >> endobj\n%%EOF"
    with pytest.raises(FormatError) as e:
        detect_and_extract("scan.pdf", scanned, "en")
    assert str(e.value) == ocr.SCANNED_PDF_MESSAGE
    text_pdf = b"%PDF-1.4\n1 0 obj << /Type /Font /Subtype /Type1 >> endobj\nBT (Hello) Tj ET\n%%EOF"
    with pytest.raises(FormatError) as e:
        detect_and_extract("contract.pdf", text_pdf, "en")
    assert str(e.value) == registry.PDF_MESSAGE


def test_ocr_stub_interface() -> None:
    with pytest.raises(FormatError, match="OCR"):
        ocr.ocr_to_docx(b"\x89PNG", "scan.png", "en")
    with pytest.raises(FormatError, match="This PDF is a scan"):
        ocr.ocr_to_docx(b"%PDF-1.4", "scan.pdf", "en")

    class FakeEngine:
        def __init__(self, out: bytes) -> None:
            self.out = out

        def to_docx(self, data: bytes, filename: str, lang: str) -> bytes:
            return self.out

    try:
        ocr.register_engine(FakeEngine(make_docx()))
        docx = ocr.ocr_to_docx(b"\x89PNG", "scan.png", "en")
        assert detect_and_extract("scan.docx", docx, "en").segment_count > 0
        ocr.register_engine(FakeEngine(b"not a document"))
        with pytest.raises(FormatError, match="did not produce a usable document"):
            ocr.ocr_to_docx(b"\x89PNG", "scan.png", "en")
    finally:
        ocr.register_engine(None)
    assert ocr.engine() is None


def test_handler_options() -> None:
    xml = b"<doc><p>Keep this</p><secret>Hide this</secret></doc>"
    assert len(detect_and_extract("a.xml", xml, "en").units) == 2
    ruled = detect_and_extract("a.xml", xml, "en", {"rules": {"exclude": ["secret"]}})
    assert [u.unit_id for u in ruled.units] == ["/doc/p#0"]
    assert detect_and_extract("a.xml", xml, "en", {}).segment_count == 2  # empty options change nothing
    with pytest.raises(FormatError, match="do not take processing options"):
        get_handler("a.docx", {"rules": {}})
    with pytest.raises(FormatError, match="must be a JSON object"):
        get_handler("a.xml", ["rules"])  # type: ignore[arg-type]
