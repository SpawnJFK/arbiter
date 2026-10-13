"""Format registry for software string files (push / pull / release bundles).

`parse(fmt, data, lang, base_lang)` and `render(fmt, doc, lang)`; `detect(filename, data)`
picks a format from the extension and, for .json and .xlf, the content.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from arbiter.strings.formats import android, apple, gettext, jsonfam, tables, xliff, yamlfmt
from arbiter.strings.formats.base import Doc, KeyRow, StringsFormatError

ParseFn = Callable[[bytes, str, str], Doc]
RenderFn = Callable[[Doc, str], bytes]


@dataclass(frozen=True)
class FormatSpec:
    name: str
    label: str
    extension: str
    content_type: str
    parse: ParseFn
    render: RenderFn
    multilingual: bool = False  # one file holds several languages
    bilingual: bool = False  # file holds the base text next to one target


FORMATS: dict[str, FormatSpec] = {
    s.name: s
    for s in (
        FormatSpec(
            "json", "JSON (flat)", "json", "application/json", jsonfam.parse_json, jsonfam.render_json
        ),
        FormatSpec(
            "json_nested",
            "JSON (nested, next-intl / vue-i18n)",
            "json",
            "application/json",
            jsonfam.parse_json,
            jsonfam.render_json_nested,
        ),
        FormatSpec(
            "i18next",
            "i18next JSON",
            "json",
            "application/json",
            jsonfam.parse_i18next,
            jsonfam.render_i18next,
        ),
        FormatSpec(
            "formatjs",
            "FormatJS / react-intl",
            "json",
            "application/json",
            jsonfam.parse_formatjs,
            jsonfam.render_formatjs,
        ),
        FormatSpec("arb", "Flutter ARB", "arb", "application/json", jsonfam.parse_arb, jsonfam.render_arb),
        FormatSpec("android", "Android strings.xml", "xml", "application/xml", android.parse, android.render),
        FormatSpec(
            "ios_strings", "iOS .strings", "strings", "text/plain", apple.parse_strings, apple.render_strings
        ),
        FormatSpec(
            "stringsdict",
            "iOS .stringsdict",
            "stringsdict",
            "application/xml",
            apple.parse_stringsdict,
            apple.render_stringsdict,
        ),
        FormatSpec(
            "xcstrings",
            "Xcode String Catalog",
            "xcstrings",
            "application/json",
            apple.parse_xcstrings,
            apple.render_xcstrings,
            multilingual=True,
        ),
        FormatSpec("yaml", "Rails YAML", "yml", "application/yaml", yamlfmt.parse, yamlfmt.render),
        FormatSpec(
            "po",
            "gettext PO",
            "po",
            "text/x-gettext-translation",
            gettext.parse,
            gettext.render,
            bilingual=True,
        ),
        FormatSpec(
            "pot",
            "gettext POT",
            "pot",
            "text/x-gettext-translation",
            lambda d, lg, b: gettext.parse(d, lg, b, template=True),
            lambda doc, lg: gettext.render(doc, lg, template=True),
        ),
        FormatSpec(
            "xliff12",
            "XLIFF 1.2",
            "xlf",
            "application/xliff+xml",
            xliff.parse,
            lambda doc, lg: xliff.render(doc, lg, version="1.2"),
            bilingual=True,
        ),
        FormatSpec(
            "xliff21",
            "XLIFF 2.1",
            "xlf",
            "application/xliff+xml",
            xliff.parse,
            lambda doc, lg: xliff.render(doc, lg, version="2.1"),
            bilingual=True,
        ),
        FormatSpec("csv", "CSV", "csv", "text/csv", tables.parse_csv, tables.render_csv, multilingual=True),
        FormatSpec(
            "xlsx",
            "Excel XLSX",
            "xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            tables.parse_xlsx,
            tables.render_xlsx,
            multilingual=True,
        ),
    )
}

_BY_EXT = {
    "arb": "arb",
    "xml": "android",
    "strings": "ios_strings",
    "stringsdict": "stringsdict",
    "xcstrings": "xcstrings",
    "yml": "yaml",
    "yaml": "yaml",
    "po": "po",
    "pot": "pot",
    "csv": "csv",
    "tsv": "csv",
    "xlsx": "xlsx",
}


def detect(filename: str, data: bytes) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "json":
        return jsonfam.sniff(data) or "json"
    if ext in ("xlf", "xliff"):
        return "xliff21" if b'version="2' in data[:2000] else "xliff12"
    if ext in _BY_EXT:
        return _BY_EXT[ext]
    raise StringsFormatError(f"Cannot tell the format of {filename!r}; pass `format` explicitly.")


def get(name: str) -> FormatSpec:
    spec = FORMATS.get(name)
    if spec is None:
        raise StringsFormatError(f"Unknown format {name!r}. Supported: {', '.join(FORMATS)}.")
    return spec


def parse(fmt: str, data: bytes, lang: str, base_lang: str) -> Doc:
    return get(fmt).parse(data, lang, base_lang)


def render(fmt: str, doc: Doc, lang: str) -> bytes:
    return get(fmt).render(doc, lang)


__all__ = ["FORMATS", "Doc", "FormatSpec", "KeyRow", "StringsFormatError", "detect", "get", "parse", "render"]
