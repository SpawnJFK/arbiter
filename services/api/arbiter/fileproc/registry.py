"""Format registry: picks a handler by file extension and applies the intake rules.

Refusals are explicit and client safe. PDF and legacy binary Office formats are refused
on purpose: their text cannot be written back reliably, and a translation the client
cannot use is worse than an honest "please send the source file".
"""

from __future__ import annotations

import posixpath
import zipfile

from lxml import etree

from arbiter.fileproc.base import ExtractionResult, FormatError, FormatHandler
from arbiter.fileproc.docx import DocxHandler
from arbiter.fileproc.html import HtmlHandler
from arbiter.fileproc.jsonfmt import JsonHandler
from arbiter.fileproc.markdown import MarkdownHandler
from arbiter.fileproc.po import PoHandler
from arbiter.fileproc.pptx import PptxHandler
from arbiter.fileproc.text import CsvHandler, TextHandler
from arbiter.fileproc.xliff import XliffHandler
from arbiter.fileproc.xlsx import XlsxHandler

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
    XliffHandler(),
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


def get_handler(filename: str) -> FormatHandler:
    ext = _extension(filename)
    handler = _BY_EXT.get(ext)
    if handler is not None:
        return handler
    if ext == "pdf":
        raise FormatError(PDF_MESSAGE)
    if ext in _LEGACY:
        raise FormatError(LEGACY_MESSAGE)
    supported = ", ".join(f".{e}" for e in SUPPORTED_EXTENSIONS)
    shown = f".{ext} files are" if ext else "Files without an extension are"
    raise FormatError(f"{shown} not supported. Supported formats: {supported}.")


def detect_and_extract(filename: str, data: bytes, source_lang: str) -> ExtractionResult:
    """Validate an upload and extract it. Every failure is a FormatError the client can read."""
    if len(data) > MAX_FILE_BYTES:
        raise FormatError("The file is larger than the 1 GB limit.")
    handler = get_handler(filename)
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
