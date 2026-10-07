"""LLM-based MT: wraps any LlmClient as an MtEngine (name ``llm-mt:<llm name>``).

Why: an LLM can take what classic MT APIs cannot (R-MT-*): glossary terms with their
kind, client style rules, formality, TM examples as few-shot guidance, neighbouring
context and a length limit, all in one request. The output still goes through the same
hard checks as any engine; the prompt asking to keep every ⟦..⟧ token is a request, the
tag QA is the guarantee.
"""

from __future__ import annotations

from arbiter.contracts import EngineError, LlmClient, MtRequest, MtResult
from arbiter.quality.prompts import PROMPT_VERSION, TRANSLATE_SYSTEM, payload


def build_translate_prompt(req: MtRequest) -> tuple[str, str]:
    user = payload(
        "translate",
        source_lang=req.source_lang,
        target_lang=req.target_lang,
        source=req.source_tagged,
        terms=[
            {"source": t.source_term, "target": t.target_term, "kind": t.kind, "note": t.note}
            for t in req.terms
        ],
        style_rules=req.style_rules,
        formality=req.formality,
        max_length=req.max_length,
        tm_examples=[
            {"source": m.source_tagged, "target": m.target_tagged, "match": m.kind, "score": m.score}
            for m in req.tm_examples
        ],
        context_before=req.context_before,
        context_after=req.context_after,
    )
    return TRANSLATE_SYSTEM, user


class LlmMt:
    supports_glossary = True

    def __init__(self, llm: LlmClient, *, max_tokens: int = 4000) -> None:
        self.llm = llm
        self.name = f"llm-mt:{llm.name}"
        self.max_tokens = max_tokens

    def available(self) -> bool:
        return self.llm.available()

    def translate(self, requests: list[MtRequest]) -> list[MtResult]:
        # One call per segment: keeps a failure local to one segment and keeps the
        # prompt small enough for strict instruction following.
        results = []
        for req in requests:
            system, user = build_translate_prompt(req)
            try:
                data, usage, model = self.llm.complete_json(
                    system, user, schema_hint='{"translation": "string"}', max_tokens=self.max_tokens
                )
            except EngineError as e:
                results.append(MtResult("", self.name, "", error=str(e)))
                continue
            text = data.get("translation")
            if not isinstance(text, str):
                results.append(
                    MtResult("", self.name, model, usage, error="llm-mt: no translation in output")
                )
                continue
            results.append(MtResult(text, self.name, f"{model}+prompt:{PROMPT_VERSION}", usage))
        return results
