"""Deterministic mock providers: MockMt, MockLlm and the ScriptedLlm test helper.

Why they exist: dev and test must run the full pipeline (translate, QA, judge, senate,
editor) with zero network and zero cost, and tests must be able to provoke every failure
path on purpose.

MockMt pseudo-translates: vowels get diacritics (a->á, e->ë, ...), so the output is
visibly "translated" and the transform is reversible, while everything QA protects is
kept byte-for-byte: code tokens, numbers, URLs, e-mails, placeholders, do-not-translate
terms; mandatory/preferred glossary terms are replaced with their target term.

Fault injection (markers in the SOURCE, removed from the output):
    {{drop_tag}}      first code token is dropped
    {{wrong_number}}  first number is incremented
    {{omit_term}}     glossary targets are not inserted (term_missing)
    {{fail}}          the engine returns an MtResult with error set
Engine-level faults can also be set with ``MockMt(faults={...})`` so best-of-N tests can
have one bad engine among good ones.

MockLlm answers the JSON prompts built in ``arbiter.quality.prompts`` (it reads the
``"task"`` key) and flags MQM errors when the TARGET contains review markers:
    {{mistranslation}}  accuracy/major       raised by judge, accuracy, terminology
    {{critical}}        accuracy/critical    raised by judge, accuracy, fluency, consistency
    {{fluency}}         linguistic_conv/minor raised by judge, fluency, accuracy
    {{style}}           style/minor          raised by judge, fluency (lone minor style)
    {{terminology}}     terminology/major    raised by judge, terminology (lone -> verified yes)
    {{spurious}}        accuracy/major       raised by accuracy only (lone -> verified no)
Review markers look like {{name}} placeholders, so put them in the source too when a
test runs the hard checks (MockMt passes placeholders through unchanged).
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from arbiter.contracts import EngineError, MtRequest, MtResult, TermHit, Usage
from arbiter.engines import tags

# ------------------------------------------------------------------------ pseudo-MT

_ACCENT = str.maketrans("aeiouAEIOU", "áëïöüÁËÏÖÜ")
_UNACCENT = str.maketrans("áëïöüÁËÏÖÜ", "aeiouAEIOU")
MT_FAULTS = ("drop_tag", "wrong_number", "omit_term", "fail")
_FAULT_RE = re.compile(r" ?\{\{(" + "|".join(MT_FAULTS) + r")\}\}")

_PROTECT = [
    r"⟦⟦|⟧⟧",
    r"⟦/?[A-Za-z0-9_.-]+/?⟧",
    r"(?:https?://|www\.)[^\s⟦⟧<>\"]+",
    r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+",
    r"\{\{[^{}]+\}\}|\$\{[^{}]+\}|\{[^{}\s]*\}|%(?:\d+\$)?[sd@]",
    r"\d+(?:[.,]\d+)*",
]


def pseudo_translate(source_tagged: str, terms: Iterable[TermHit] = (), faults: Iterable[str] = ()) -> str:
    """Deterministic, tag-preserving pseudo-translation used by MockMt and MockLlm."""
    fault_set = set(faults) | set(_FAULT_RE.findall(source_tagged))
    text = _FAULT_RE.sub("", source_tagged)
    term_list = sorted(
        (t for t in terms if t.kind != "forbidden"), key=lambda t: len(t.source_term), reverse=True
    )
    parts = [f"(?P<p{i}>{p})" for i, p in enumerate(_PROTECT)]
    parts += [
        f"(?P<t{i}>(?<!\\w){re.escape(t.source_term)}(?!\\w))"
        for i, t in enumerate(term_list)
        if t.source_term
    ]
    master = re.compile("|".join(parts), re.I) if parts else None
    out: list[str] = []
    pos = 0
    number_done = False
    assert master is not None
    for m in master.finditer(text):
        out.append(text[pos : m.start()].translate(_ACCENT))
        pos = m.end()
        group = m.lastgroup or ""
        value = m.group(0)
        if group == f"p{len(_PROTECT) - 1}" and "wrong_number" in fault_set and not number_done:
            digits = re.sub(r"\D", "", value)
            value = str(int(digits) + 1) if digits else value
            number_done = True
        elif group.startswith("t"):
            term = term_list[int(group[1:])]
            if term.kind == "do_not_translate":
                pass  # keep source form
            elif "omit_term" in fault_set or not term.target_term:
                value = value.translate(_ACCENT)
            else:
                value = term.target_term
        out.append(value)
    out.append(text[pos:].translate(_ACCENT))
    result = "".join(out)
    if "drop_tag" in fault_set:
        toks = tags.token_list(result)
        if toks:
            result = result.replace(toks[0], "", 1)
    return result


def unpseudo(text: str) -> str:
    """Inverse of the vowel transform (glossary replacements are not reversed)."""
    return text.translate(_UNACCENT)


class MockMt:
    """Deterministic MtEngine. Always available, zero cost."""

    supports_glossary = True

    def __init__(
        self, name: str = "mock-mt", *, faults: Iterable[str] = (), model_version: str = "mock-mt-1"
    ):
        self.name = name
        self.faults = frozenset(faults)
        self.model_version = model_version

    def available(self) -> bool:
        return True

    def translate(self, requests: list[MtRequest]) -> list[MtResult]:
        results = []
        for r in requests:
            chars = len(tags.plain(r.source_tagged))
            if "fail" in self.faults or "{{fail}}" in r.source_tagged:
                results.append(
                    MtResult("", self.name, self.model_version, Usage(), error="mock-mt: injected failure")
                )
                continue
            target = pseudo_translate(r.source_tagged, r.terms, self.faults)
            results.append(MtResult(target, self.name, self.model_version, Usage(characters=chars)))
        return results


# ------------------------------------------------------------------------ mock LLM

REVIEW_MARKERS: dict[str, tuple[str, str, frozenset[str]]] = {
    "mistranslation": ("accuracy", "major", frozenset({"judge", "accuracy", "terminology"})),
    "critical": ("accuracy", "critical", frozenset({"judge", "accuracy", "fluency", "consistency"})),
    "fluency": ("linguistic_conventions", "minor", frozenset({"judge", "fluency", "accuracy"})),
    "style": ("style", "minor", frozenset({"judge", "fluency"})),
    "terminology": ("terminology", "major", frozenset({"judge", "terminology"})),
    "spurious": ("accuracy", "major", frozenset({"accuracy"})),
}
_MARKER_RE = re.compile(r"\{\{(" + "|".join(REVIEW_MARKERS) + r")\}\}")


def _usage(system: str, user: str, answer: dict[str, Any]) -> Usage:
    return Usage(input_tokens=(len(system) + len(user)) // 4, output_tokens=len(json.dumps(answer)) // 4)


def _parse_payload(user: str) -> dict[str, Any]:
    try:
        data = json.loads(user)
    except ValueError as e:
        raise EngineError(f"mock-llm: user prompt is not JSON: {e}") from e
    if not isinstance(data, dict) or "task" not in data:
        raise EngineError("mock-llm: no task in prompt")
    return data


class MockLlm:
    """Deterministic LlmClient understanding our own prompt protocol.

    ``fail_on`` lists roles/tasks for which it raises EngineError (simulates an outage).
    """

    def __init__(
        self, name: str = "mock-llm", *, fail_on: Iterable[str] = (), model_version: str = "mock-llm-1"
    ):
        self.name = name
        self.fail_on = frozenset(fail_on)
        self.model_version = model_version

    def available(self) -> bool:
        return True

    def complete_json(
        self,
        system: str,
        user: str,
        *,
        schema_hint: str = "",
        max_tokens: int = 2000,
        temperature: float = 0.0,
    ) -> tuple[dict[str, Any], Usage, str]:
        data = _parse_payload(user)
        task = str(data["task"])
        role = str(data.get("role") or ("judge" if task == "judge" else task))
        if task in self.fail_on or role in self.fail_on:
            raise EngineError(f"mock-llm: injected failure for {role}")
        answer = self._answer(task, role, data)
        return answer, _usage(system, user, answer), self.model_version

    def _answer(self, task: str, role: str, data: dict[str, Any]) -> dict[str, Any]:
        if task in ("judge", "senate_role"):
            target = str(data.get("target", ""))
            errors = []
            for m in _MARKER_RE.finditer(target):
                dim, sev, roles = REVIEW_MARKERS[m.group(1)]
                if role in roles:
                    errors.append(
                        {
                            "dimension": dim,
                            "severity": sev,
                            "span": m.group(0),
                            "explanation": f"mock: {m.group(1)} marker",
                            "fix": "",
                        }
                    )
            return {"errors": errors}
        if task == "verify":
            improves = "{{spurious}}" not in str(data.get("span", ""))
            return {"improves": improves, "reason": "mock verification"}
        if task == "edit":
            target = str(data.get("target", ""))
            if "{{edit_drop_tag}}" in target:
                toks = tags.token_list(target)
                if toks:
                    target = target.replace(toks[0], "", 1)
            target = re.sub(r" ?\{\{(?:" + "|".join(REVIEW_MARKERS) + r"|edit_drop_tag)\}\}", "", target)
            return {"target": target}
        if task == "triage":
            labels = []
            for w in data.get("warnings", []):
                fp = w.get("code") == "repeated_word"
                labels.append(
                    {
                        "id": w.get("id"),
                        "label": "false_positive" if fp else "real",
                        "reason": "mock: reduplication can be intentional" if fp else "mock: keep",
                    }
                )
            return {"labels": labels}
        if task == "translate":
            terms = [
                TermHit(
                    term_id=str(i),
                    kind=t.get("kind", "mandatory"),
                    source_term=t.get("source", ""),
                    target_term=t.get("target"),
                    start=0,
                    end=0,
                )
                for i, t in enumerate(data.get("terms", []))
            ]
            return {"translation": pseudo_translate(str(data.get("source", "")), terms)}
        raise EngineError(f"mock-llm: unknown task {task!r}")


# ------------------------------------------------------------------------ scripted LLM

Response = dict[str, Any] | Exception | Callable[[dict[str, Any], str, str], dict[str, Any]]


class ScriptedLlm:
    """Test helper: returns queued responses per role (or task), records every call.

    Lookup key for a call: the payload's ``role`` if present, else its ``task``, else
    "*". Each key has a FIFO queue; an Exception entry is raised, a callable entry is
    called with (payload, system, user). When a queue is empty the ``default`` response is
    used; without a default the call raises EngineError, so an unexpected call is loud.
    Thread-safe because senate roles run concurrently.
    """

    def __init__(
        self,
        script: Mapping[str, list[Response]] | None = None,
        *,
        default: Response | None = None,
        name: str = "scripted",
        model_version: str = "scripted-1",
    ) -> None:
        self.name = name
        self.model_version = model_version
        self.queues: dict[str, list[Response]] = {k: list(v) for k, v in (script or {}).items()}
        self.default = default
        self.calls: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def available(self) -> bool:
        return True

    def calls_for(self, key: str) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["key"] == key]

    def complete_json(
        self,
        system: str,
        user: str,
        *,
        schema_hint: str = "",
        max_tokens: int = 2000,
        temperature: float = 0.0,
    ) -> tuple[dict[str, Any], Usage, str]:
        try:
            data = json.loads(user)
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        with self._lock:
            key = str(data.get("role") or data.get("task") or "*")
            self.calls.append({"key": key, "system": system, "user": user, "payload": data})
            queue = None
            for k in (key, str(data.get("task", "")), "*"):
                if self.queues.get(k):
                    queue = self.queues[k]
                    break
            resp = queue.pop(0) if queue else self.default
        if resp is None:
            raise EngineError(f"scripted-llm: no response queued for {key!r}")
        if isinstance(resp, Exception):
            raise resp
        answer = resp(data, system, user) if callable(resp) else resp
        return answer, _usage(system, user, answer), self.model_version
