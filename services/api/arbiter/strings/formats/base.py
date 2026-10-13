"""Canonical model for key-value resource files (software strings).

Every format parses into a `Doc`: a list of `KeyRow`s, each with values per language.
Single-language formats (JSON, ARB, Android, iOS .strings, YAML, ...) fill one language;
bilingual and multilingual ones (PO, XLIFF, .xcstrings, CSV, XLSX) fill several. Rendering
takes a Doc and a language. This is deliberately separate from arbiter.fileproc, which
models documents (paragraphs, inline formatting) rather than keyed resources.

Value shape by kind:
    string   str
    plural   dict[CLDR category or "=N", str]
    array    dict["0".."n", str]           (Android string-array)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Kind = Literal["string", "plural", "array"]
Value = str | dict[str, str]


class StringsFormatError(ValueError):
    """The file cannot be parsed. The message is safe to show the user (R-STR-IN-01)."""


@dataclass
class KeyRow:
    key: str
    namespace: str = ""
    kind: Kind = "string"
    description: str = ""
    max_length: int | None = None
    translatable: bool = True
    tags: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    values: dict[str, Value] = field(default_factory=dict)  # lang -> value
    states: dict[str, str] = field(default_factory=dict)  # lang -> untranslated|machine|reviewed|approved

    @property
    def ident(self) -> tuple[str, str]:
        return (self.namespace, self.key)


@dataclass
class Doc:
    base_lang: str
    rows: list[KeyRow] = field(default_factory=list)
    langs: list[str] = field(default_factory=list)  # languages present (parse) or wanted (render)
    warnings: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def lang_rows(self, lang: str) -> list[KeyRow]:
        return [r for r in self.rows if lang in r.values]


def as_forms(value: Value | None) -> dict[str, str]:
    if isinstance(value, dict):
        return dict(value)
    return {"other": value} if value is not None else {}


def as_text(value: Value | None) -> str:
    if isinstance(value, dict):
        return value.get("other") or next(iter(value.values()), "")
    return value or ""


def decode(data: bytes) -> str:
    """UTF-8 (BOM tolerated) or UTF-16 with BOM; anything else is refused."""
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise StringsFormatError("The file is not UTF-8 or UTF-16 text.") from None


PLURAL_KEYS = frozenset({"zero", "one", "two", "few", "many", "other"})


def is_plural_map(obj: Any) -> bool:
    """A mapping of CLDR categories (must include `other`) to strings."""
    return (
        isinstance(obj, dict)
        and bool(obj)
        and "other" in obj
        and all(isinstance(k, str) and (k in PLURAL_KEYS or k.startswith("=")) for k in obj)
        and all(isinstance(v, str) for v in obj.values())
    )
