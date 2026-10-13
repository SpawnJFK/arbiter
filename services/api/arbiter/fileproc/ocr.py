"""Scanned documents: the OCR-to-DOCX interface, deliberately without an engine (stub).

Text PDFs stay refused (registry.PDF_MESSAGE): the translation could not be written
back reliably. Scanned PDFs and images are a different case: there is no text to write
back at all, so the only honest route is optical character recognition into an
editable DOCX, which is then translated like any DOCX.

No OCR engine is installed. This module fixes the seam so one can be added without
touching callers:

    class MyOcr:
        def to_docx(self, data: bytes, filename: str, lang: str) -> bytes: ...

    ocr.register_engine(MyOcr())

Until an engine is registered, ocr_to_docx() raises a FormatError that tells the
client to upload the source file. detect_and_extract() never calls OCR on its own: a
caller that wants the OCR route converts first and then extracts the returned DOCX,
so quoting and provenance can record that the text came from OCR.
"""

from __future__ import annotations

import re
from typing import Protocol

from arbiter.fileproc.base import FormatError

IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {"png", "jpg", "jpeg", "tif", "tiff", "bmp", "gif", "webp", "heic"}
)

SCANNED_PDF_MESSAGE = (
    "This PDF is a scan and contains no text that can be translated. Text recognition (OCR) is not "
    "available. Please upload the original source file (DOCX, PPTX, XLSX, InDesign...)."
)
IMAGE_MESSAGE = (
    "Image files contain no text that can be translated. Text recognition (OCR) is not available. "
    "Please upload the original source file (DOCX, PPTX, XLSX, InDesign...)."
)


class OcrEngine(Protocol):
    """Turns a scanned PDF or an image into an editable DOCX in the given language."""

    def to_docx(self, data: bytes, filename: str, lang: str) -> bytes: ...


_ENGINE: OcrEngine | None = None


def register_engine(engine: OcrEngine | None) -> None:
    """Install (or with None remove) the OCR engine. Not called anywhere yet."""
    global _ENGINE
    _ENGINE = engine


def engine() -> OcrEngine | None:
    return _ENGINE


_FONT = re.compile(rb"/Font\b|/Type\s*/Font\b")
_IMAGE = re.compile(rb"/Subtype\s*/Image\b")
_TEXT_OP = re.compile(rb"\bBT\b[\s\S]{0,400}?\bTj\b|\bTJ\b")


def looks_scanned_pdf(data: bytes) -> bool:
    """Heuristic: images and no fonts anywhere in the file means a scan without a text layer.

    Compressed object streams can hide font dictionaries, so the answer is a hint for the
    error message, never a reason to accept a file.
    """
    if not data.startswith(b"%PDF"):
        return False
    return bool(_IMAGE.search(data)) and not _FONT.search(data) and not _TEXT_OP.search(data)


def message_for(ext: str, data: bytes | None = None) -> str | None:
    """The refusal for a scanned input, or None when the file is not a scan or image."""
    if ext in IMAGE_EXTENSIONS:
        return IMAGE_MESSAGE
    if ext == "pdf" and data is not None and looks_scanned_pdf(data):
        return SCANNED_PDF_MESSAGE
    return None


def ocr_to_docx(data: bytes, filename: str, lang: str) -> bytes:
    """Convert a scan to DOCX with the registered engine, or refuse with a client-safe message."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    current = _ENGINE
    if current is None:
        raise FormatError(IMAGE_MESSAGE if ext in IMAGE_EXTENSIONS else SCANNED_PDF_MESSAGE)
    out = current.to_docx(data, filename, lang)
    if not out.startswith(b"PK"):
        raise FormatError(
            "Text recognition did not produce a usable document. Please upload the source file."
        )
    return out
