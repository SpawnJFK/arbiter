"""String-specific hard QA (R-STR-QA-*), on top of quality.checks for engine output.

Codes (all blocking except where noted):
    empty_value            the translation (or a form) is empty while the source is not
    placeholder_changed    a placeholder is missing or added (R-STR-QA-01). In a plural form a
                           MISSING placeholder is only a warning ("one {one file}" drops #/%d
                           legitimately); an added unknown one is still blocking.
    icu_syntax             the value is not valid ICU MessageFormat (R-STR-QA-02)
    icu_structure          plural/select arguments differ from the source
    plural_forms_missing   a form the target language needs is missing (R-STR-QA-03)
    length_exceeded        longer than the key's max_length (R-STR-QA-04)
    array_length           an array translation has a different number of items (warning)

Blocking issues mark the translation `blocked`: it is never shipped in a release and the
app falls back to the base language (R-STR-08).
"""

from __future__ import annotations

from typing import Any

from arbiter.strings import placeholders as ph
from arbiter.strings import plurals
from arbiter.strings.formats.base import Value


def _issue(code: str, message: str, blocking: bool = True, form: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "code": code,
        "severity": "error" if blocking else "warning",
        "message": message,
        "blocking": blocking,
    }
    if form is not None:
        out["form"] = form
    return out


def _check_text(
    source: str, target: str, style: str, *, form: str | None, plural_form: bool, max_length: int | None
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not target.strip() and source.strip():
        return [_issue("empty_value", "the translation is empty", form=form)]
    missing, added = ph.diff(source, target, style)
    if added:
        issues.append(_issue("placeholder_changed", "not in the source: " + ", ".join(added), form=form))
    if missing:
        issues.append(
            _issue(
                "placeholder_changed",
                "missing: " + ", ".join(missing),
                blocking=not plural_form,
                form=form,
            )
        )
    if style != "none":
        err = ph.icu_valid(target) if ph.icu_valid(source) is None else None
        if err:
            issues.append(_issue("icu_syntax", err, form=form))
        else:
            try:
                s_sk, t_sk = ph.icu_skeleton(source), ph.icu_skeleton(target)
            except ph.IcuError:
                s_sk, t_sk = [], []
            if [(a, k) for a, k, _ in s_sk] != [(a, k) for a, k, _ in t_sk]:
                issues.append(
                    _issue("icu_structure", "plural/select arguments differ from the source", form=form)
                )
            else:
                for (arg, kind, ssel), (_, _, tsel) in zip(s_sk, t_sk, strict=True):
                    if "other" in ssel and "other" not in tsel:
                        issues.append(
                            _issue("icu_structure", f"{arg}: the 'other' branch is missing", form=form)
                        )
                    if kind == "select" and set(ssel) - set(tsel):
                        issues.append(
                            _issue(
                                "icu_structure",
                                f"{arg}: select branches missing: {', '.join(sorted(set(ssel) - set(tsel)))}",
                                form=form,
                            )
                        )
    if max_length is not None and len(target) > max_length:
        issues.append(_issue("length_exceeded", f"{len(target)} characters, limit {max_length}", form=form))
    return issues


def check_value(
    key: Any,
    base: Value | None,
    value: Value | None,
    lang: str,
    *,
    style: str = "auto",
    rules: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    """QA of one translation value against the base-language value of the key."""
    if value is None or base is None:
        return []
    kind = key.kind
    max_length = key.max_length
    if kind == "string":
        if not isinstance(value, str) or not isinstance(base, str):
            return [_issue("empty_value", "value shape does not match the key kind")]
        return _check_text(base, value, style, form=None, plural_form=False, max_length=max_length)
    base_forms = base if isinstance(base, dict) else {"other": base}
    forms = value if isinstance(value, dict) else {"other": value}
    issues: list[dict[str, Any]] = []
    if kind == "plural":
        needed = plurals.required(lang, rules)
        missing = [c for c in needed if not forms.get(c)]
        if missing:
            issues.append(_issue("plural_forms_missing", "missing forms: " + ", ".join(missing)))
        # Placeholders may differ between the source's forms; a form may use any of them.
        union = " ".join(base_forms.values())
        for form, text in forms.items():
            src = base_forms.get(plurals.source_form_for(form, base_forms) or "other", union)
            for i in _check_text(src, text, style, form=form, plural_form=True, max_length=max_length):
                if i["code"] == "placeholder_changed" and i["blocking"]:
                    _, added = ph.diff(union, text, style)
                    if not added:
                        continue  # placeholder exists in another source form: fine
                issues.append(i)
        return issues
    # array
    if len(forms) != len(base_forms):
        issues.append(
            _issue("array_length", f"{len(forms)} items, the source has {len(base_forms)}", blocking=False)
        )
    for idx, text in forms.items():
        if idx in base_forms:
            issues.extend(
                _check_text(base_forms[idx], text, style, form=idx, plural_form=False, max_length=max_length)
            )
    return issues


def blocking(issues: list[dict[str, Any]]) -> bool:
    return any(i.get("blocking") for i in issues)
