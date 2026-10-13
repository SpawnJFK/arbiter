"""CLDR cardinal plural categories per language (R-STR-PL-01).

`categories(lang)` lists the forms a translation of a plural key must provide, in CLDR
order (zero, one, two, few, many, other). `optional(lang)` lists forms a file may carry but
QA does not require: the CLDR "many" of French, Spanish, Italian, Portuguese and Catalan is
only used for compact large numbers ("1 million"), and almost no app ships it; the "many"
of Czech and Slovak is for decimals.

`gettext_forms(lang)` is the order of msgstr[0..n] in a PO file for that language (the
Plural-Forms formula index), which is not always the CLDR order.

A project can override the categories per language in settings["plural_rules"].
"""

from __future__ import annotations

ORDER = ("zero", "one", "two", "few", "many", "other")

_CLDR: dict[str, tuple[str, ...]] = {
    "af": ("one", "other"),
    "ar": ("zero", "one", "two", "few", "many", "other"),
    "az": ("one", "other"),
    "be": ("one", "few", "many", "other"),
    "bg": ("one", "other"),
    "bn": ("one", "other"),
    "bs": ("one", "few", "other"),
    "ca": ("one", "many", "other"),
    "cs": ("one", "few", "many", "other"),
    "cy": ("zero", "one", "two", "few", "many", "other"),
    "da": ("one", "other"),
    "de": ("one", "other"),
    "el": ("one", "other"),
    "en": ("one", "other"),
    "es": ("one", "many", "other"),
    "et": ("one", "other"),
    "eu": ("one", "other"),
    "fa": ("one", "other"),
    "fi": ("one", "other"),
    "fil": ("one", "other"),
    "fr": ("one", "many", "other"),
    "ga": ("one", "two", "few", "many", "other"),
    "gd": ("one", "two", "few", "other"),
    "gl": ("one", "other"),
    "he": ("one", "two", "other"),
    "hi": ("one", "other"),
    "hr": ("one", "few", "other"),
    "hu": ("one", "other"),
    "hy": ("one", "other"),
    "id": ("other",),
    "is": ("one", "other"),
    "it": ("one", "many", "other"),
    "ja": ("other",),
    "ka": ("one", "other"),
    "kk": ("one", "other"),
    "km": ("other",),
    "ko": ("other",),
    "lt": ("one", "few", "many", "other"),
    "lv": ("zero", "one", "other"),
    "mk": ("one", "other"),
    "ms": ("other",),
    "mt": ("one", "two", "few", "many", "other"),
    "nb": ("one", "other"),
    "nl": ("one", "other"),
    "nn": ("one", "other"),
    "no": ("one", "other"),
    "pl": ("one", "few", "many", "other"),
    "pt": ("one", "many", "other"),
    "ro": ("one", "few", "other"),
    "ru": ("one", "few", "many", "other"),
    "sk": ("one", "few", "many", "other"),
    "sl": ("one", "two", "few", "other"),
    "sq": ("one", "other"),
    "sr": ("one", "few", "other"),
    "sv": ("one", "other"),
    "sw": ("one", "other"),
    "ta": ("one", "other"),
    "th": ("other",),
    "tr": ("one", "other"),
    "uk": ("one", "few", "many", "other"),
    "ur": ("one", "other"),
    "uz": ("one", "other"),
    "vi": ("other",),
    "zh": ("other",),
}
_OPTIONAL: dict[str, frozenset[str]] = {
    "ca": frozenset({"many"}),
    "es": frozenset({"many"}),
    "fr": frozenset({"many"}),
    "it": frozenset({"many"}),
    "pt": frozenset({"many"}),
    "cs": frozenset({"many"}),
    "sk": frozenset({"many"}),
    "lt": frozenset({"many"}),
}
_GETTEXT: dict[str, tuple[str, ...]] = {
    "be": ("one", "few", "many"),
    "ru": ("one", "few", "many"),
    "uk": ("one", "few", "many"),
    "pl": ("one", "few", "many"),
    "cs": ("one", "few", "other"),
    "sk": ("one", "few", "other"),
    "lt": ("one", "few", "other"),
    "fr": ("one", "other"),
    "es": ("one", "other"),
    "it": ("one", "other"),
    "pt": ("one", "other"),
    "ca": ("one", "other"),
}


def primary(lang: str) -> str:
    return lang.replace("_", "-").split("-")[0].lower()


def categories(lang: str, overrides: dict[str, list[str]] | None = None) -> tuple[str, ...]:
    """All CLDR cardinal categories of a language (unknown languages: one, other)."""
    if overrides:
        for key in (lang, primary(lang)):
            if key in overrides and overrides[key]:
                return tuple(c for c in ORDER if c in set(overrides[key]))
    return _CLDR.get(primary(lang), ("one", "other"))


def optional(lang: str) -> frozenset[str]:
    return _OPTIONAL.get(primary(lang), frozenset())


def required(lang: str, overrides: dict[str, list[str]] | None = None) -> tuple[str, ...]:
    """Forms QA requires for a plural translation (R-STR-PL-01)."""
    opt = frozenset() if overrides and (lang in overrides or primary(lang) in overrides) else optional(lang)
    return tuple(c for c in categories(lang, overrides) if c not in opt)


def gettext_forms(lang: str) -> tuple[str, ...]:
    """Category of msgstr[i] in a PO file for `lang`."""
    return _GETTEXT.get(primary(lang), required(lang))


def source_form_for(category: str, source_forms: dict[str, str]) -> str | None:
    """Which source form a target category is translated from (R-STR-PL-02).

    The same category when the source has it (one -> one), else `other`. Explicit ICU
    selectors (=0, =1) map only to themselves.
    """
    if category in source_forms:
        return category
    if category.startswith("="):
        return None
    if "other" in source_forms:
        return "other"
    return next(iter(source_forms), None)


def sort_forms(forms: dict[str, str]) -> dict[str, str]:
    """Explicit selectors first (=0, =1), then CLDR order, then anything else; stable."""

    def rank(k: str) -> tuple[int, int, str]:
        if k.startswith("="):
            return (0, int(k[1:]) if k[1:].isdigit() else 0, k)
        if k in ORDER:
            return (1, ORDER.index(k), k)
        return (2, 0, k)

    return {k: forms[k] for k in sorted(forms, key=rank)}
