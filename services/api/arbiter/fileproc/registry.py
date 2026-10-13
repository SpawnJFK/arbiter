"""Format registry: picks a handler by file extension and applies the intake rules.

Refusals are explicit and client safe. PDF and legacy binary Office formats are refused
on purpose: their text cannot be written back reliably, and a translation the client
cannot use is worse than an honest "please send the source file". Scanned PDFs and
images get their own message; the OCR-to-DOCX seam is in ocr.py (no engine installed).

Handler options: get_handler() and detect_and_extract() take an optional options
mapping (for example XML rules or a subtitle line limit). A handler that supports
options has a configure(options) method returning a configured copy; passing options to
a handler without one is refused. The same options must be used for extract and merge,
so callers that accept options per upload must store them with the file.
"""

from __future__ import annotations

import posixpath
import zipfile
from collections.abc import Mapping
from typing import Any

from lxml import etree

from arbiter.fileproc import ocr
from arbiter.fileproc.asciidoc import AsciidocHandler
from arbiter.fileproc.base import ExtractionResult, FormatError, FormatHandler
from arbiter.fileproc.docx import DocxHandler
from arbiter.fileproc.html import HtmlHandler
from arbiter.fileproc.idml import IdmlHandler
from arbiter.fileproc.jsonfmt import JsonHandler
from arbiter.fileproc.markdown import MarkdownHandler
from arbiter.fileproc.po import PoHandler
from arbiter.fileproc.pptx import PptxHandler
from arbiter.fileproc.resources import (
    ArbHandler,
    PropertiesHandler,
    ResxHandler,
    StringsdictHandler,
    StringsHandler,
)
from arbiter.fileproc.subtitles import AssHandler, SrtHandler, VttHandler
from arbiter.fileproc.text import CsvHandler, TextHandler, TsvHandler
from arbiter.fileproc.xliff import XliffHandler
from arbiter.fileproc.xlsx import XlsxHandler
from arbiter.fileproc.xmlfmt import DitaHandler, XmlHandler
from arbiter.fileproc.yamlfmt import YamlHandler

MAX_FILE_BYTES = 1024 * 1024 * 1024  # R-IN-03

HANDLERS: list[FormatHandler] = [
    DocxHandler(),
    XlsxHandler(),
    PptxHandler(),
    HtmlHandler(),
    MarkdownHandler(),
    JsonHandler(),
    PoHandler(),
    TextHandler(),
    CsvHandler(),
    TsvHandler(),
    XliffHandler(),
    IdmlHandler(),
    SrtHandler(),
    VttHandler(),
    AssHandler(),
    XmlHandler(),
    DitaHandler(),
    ArbHandler(),
    StringsHandler(),
    StringsdictHandler(),
    PropertiesHandler(),
    ResxHandler(),
    YamlHandler(),
    AsciidocHandler(),
]

_BY_EXT: dict[str, FormatHandler] = {ext: h for h in HANDLERS for ext in h.extensions}
SUPPORTED_EXTENSIONS: tuple[str, ...] = tuple(sorted(_BY_EXT))

PDF_MESSAGE = (
    "PDF files are not supported because the result would not be reliable. "
    "Please upload the original document (DOCX, PPTX, XLSX, HTML...)."
)
LEGACY_MESSAGE = (
    "Legacy Office formats are not supported. Save the file as .docx/.xlsx/.pptx and upload it again."
)
EMPTY_MESSAGE = "The file contains no translatable text."
_LEGACY = {"doc", "xls", "ppt", "rtf", "dot", "xlt", "pps"}


def _extension(filename: str) -> str:
    base = posixpath.basename(filename.replace("\\", "/"))
    if "." not in base:
        return ""
    return base.rsplit(".", 1)[1].lower()


def get_handler(filename: str, options: Mapping[str, Any] | None = None) -> FormatHandler:
    ext = _extension(filename)
    handler = _BY_EXT.get(ext)
    if handler is not None:
        return _configured(handler, options)
    if ext == "pdf":
        raise FormatError(PDF_MESSAGE)
    if ext in _LEGACY:
        raise FormatError(LEGACY_MESSAGE)
    scanned = ocr.message_for(ext)
    if scanned is not None:
        raise FormatError(scanned)
    supported = ", ".join(f".{e}" for e in SUPPORTED_EXTENSIONS)
    shown = f".{ext} files are" if ext else "Files without an extension are"
    raise FormatError(f"{shown} not supported. Supported formats: {supported}.")


def _configured(handler: FormatHandler, options: Mapping[str, Any] | None) -> FormatHandler:
    if not options:
        return handler
    if not isinstance(options, Mapping):
        raise FormatError("File processing options must be a JSON object.")
    configure = getattr(handler, "configure", None)
    if configure is None:
        raise FormatError(f"{handler.name.upper()} files do not take processing options.")
    configured: FormatHandler = configure(options)
    return configured


def detect_and_extract(
    filename: str, data: bytes, source_lang: str, options: Mapping[str, Any] | None = None
) -> ExtractionResult:
    """Validate an upload and extract it. Every failure is a FormatError the client can read."""
    if len(data) > MAX_FILE_BYTES:
        raise FormatError("The file is larger than the 1 GB limit.")
    if _extension(filename) == "pdf":
        raise FormatError(ocr.message_for("pdf", data) or PDF_MESSAGE)
    handler = get_handler(filename, options)
    if not data.strip():
        raise FormatError(EMPTY_MESSAGE)
    try:
        result = handler.extract(data, source_lang)
    except FormatError:
        raise
    except (
        ValueError,
        KeyError,
        IndexError,
        UnicodeError,
        RecursionError,
        OSError,
        AssertionError,
        zipfile.BadZipFile,
        etree.LxmlError,
    ):
        raise FormatError(
            f"The file could not be read. It may be damaged or not a valid {handler.name.upper()} file."
        ) from None
    if result.segment_count == 0:
        raise FormatError(EMPTY_MESSAGE)
    return result
