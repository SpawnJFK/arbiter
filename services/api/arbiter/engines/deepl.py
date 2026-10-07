"""DeepL MT engine (MtEngine).

Only active when ARBITER_DEEPL_API_KEY is set (keys ending in ":fx" use the free API host).

Tag handling: our ⟦n⟧ tokens are converted to XML before sending, with
``tag_handling=xml``, and converted back after. Paired codes become real elements
``<g id="1">…</g>`` (DeepL moves whole elements with the words they wrap, which gives
better placement than opaque placeholders); standalone codes become ``<x id="2"/>``. If
the source pairs are not properly nested, every code is sent as a self-closing
``<bx/>``/``<ex/>``/``<x/>`` so DeepL never receives invalid XML. Text is XML-escaped.

Glossary: DeepL glossaries are server-side objects created per language pair ahead of
time (POST /v2/glossaries) and referenced by ``glossary_id``. Per-segment TermHits cannot
be passed inline, so ``supports_glossary`` is False: term adherence for DeepL output is
enforced afterwards by the hard checks (term_missing is blocking). A future version can
sync the job's frozen glossary version to a DeepL glossary and pass its id
(``glossary_id`` constructor argument is already accepted).
"""

from __future__ import annotations

import html
import re

import httpx

from arbiter.config import Settings, get_settings
from arbiter.contracts import EngineError, MtRequest, MtResult, Usage
from arbiter.engines import tags
from arbiter.engines.http import check_response, with_retry
from arbiter.engines.pricing import estimate_cost

PRO_URL = "https://api.deepl.com/v2/translate"
FREE_URL = "https://api-free.deepl.com/v2/translate"
BATCH = 50  # DeepL accepts up to 50 texts per request

_FORMALITY = {"formal": "prefer_more", "informal": "prefer_less", "more": "more", "less": "less"}


def to_xml(tagged: str) -> str:
    """Tagged text -> XML fragment for DeepL."""
    paired = tags.is_balanced_tagged(tagged)
    out: list[str] = []
    for kind, value in tags.pieces(tagged):
        if kind == "text":
            assert isinstance(value, str)
            out.append(html.escape(value, quote=False))
            continue
        assert isinstance(value, tuple)
        cid, ckind = value
        cid_attr = html.escape(cid, quote=True)
        if ckind == "standalone":
            out.append(f'<x id="{cid_attr}"/>')
        elif paired:
            out.append(f'<g id="{cid_attr}">' if ckind == "open" else "</g>")
        else:
            out.append(f'<bx id="{cid_attr}"/>' if ckind == "open" else f'<ex id="{cid_attr}"/>')
    return "".join(out)


_XML_TAG_RE = re.compile(r'<(/?)(g|x|bx|ex)(?:\s+id="([^"]*)")?\s*(/?)>')


def from_xml(xml: str) -> str:
    """DeepL XML output -> tagged text. Unknown markup is kept as (escaped) text so the
    tag QA check, not this converter, decides whether the output is acceptable."""
    out: list[str] = []
    stack: list[str] = []
    pos = 0
    for m in _XML_TAG_RE.finditer(xml):
        out.append(tags.escape_text(html.unescape(xml[pos : m.start()])))
        pos = m.end()
        closing, name, cid = m.group(1), m.group(2), html.unescape(m.group(3) or "")
        if name == "g" and closing:
            out.append(f"⟦/{stack.pop()}⟧" if stack else "")
        elif name == "g":
            stack.append(cid)
            out.append(f"⟦{cid}⟧")
        elif name == "x":
            out.append(f"⟦{cid}/⟧")
        elif name == "bx":
            out.append(f"⟦{cid}⟧")
        elif name == "ex":
            out.append(f"⟦/{cid}⟧")
    out.append(tags.escape_text(html.unescape(xml[pos:])))
    return "".join(out)


class DeepLEngine:
    name = "deepl"
    supports_glossary = False

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        api_key: str | None = None,
        http_client: httpx.Client | None = None,
        glossary_id: str | None = None,
        attempts: int = 4,
        backoff: float = 1.0,
        timeout: float = 60.0,
    ) -> None:
        s = settings or get_settings()
        self.api_key = s.deepl_api_key if api_key is None else api_key
        self.glossary_id = glossary_id
        self._http = http_client
        self.attempts = attempts
        self.backoff = backoff
        self.timeout = timeout

    def available(self) -> bool:
        return bool(self.api_key)

    @property
    def url(self) -> str:
        return FREE_URL if self.api_key.endswith(":fx") else PRO_URL

    def _client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(timeout=self.timeout)
        return self._http

    def translate(self, requests: list[MtRequest]) -> list[MtResult]:
        if not self.available():
            raise EngineError("deepl: no API key configured")
        results: list[MtResult | None] = [None] * len(requests)
        # Group by everything that is a request-level parameter in the DeepL API.
        # Context is request-level in DeepL, so segments with different context cannot share a call.
        groups: dict[tuple[str, str, str | None, str], list[int]] = {}
        for i, r in enumerate(requests):
            groups.setdefault((r.source_lang, r.target_lang, r.formality, r.context_before), []).append(i)
        for (src, tgt, formality, context), idxs in groups.items():
            for start in range(0, len(idxs), BATCH):
                chunk = idxs[start : start + BATCH]
                chunk_results = self._translate_chunk(
                    [requests[i] for i in chunk], src, tgt, formality, context
                )
                for i, res in zip(chunk, chunk_results, strict=True):
                    results[i] = res
        return [r for r in results if r is not None]

    def _translate_chunk(
        self, reqs: list[MtRequest], src: str, tgt: str, formality: str | None, context: str
    ) -> list[MtResult]:
        body: dict[str, object] = {
            "text": [to_xml(r.source_tagged) for r in reqs],
            "source_lang": src.split("-")[0].upper(),
            "target_lang": tgt.upper(),
            "tag_handling": "xml",
            "ignore_tags": ["x", "bx", "ex"],
        }
        if formality and formality in _FORMALITY:
            body["formality"] = _FORMALITY[formality]
        if self.glossary_id:
            body["glossary_id"] = self.glossary_id
        if context:
            body["context"] = context
        headers = {"authorization": f"DeepL-Auth-Key {self.api_key}", "content-type": "application/json"}

        def call() -> dict:
            resp = self._client().post(self.url, json=body, headers=headers)
            check_response(resp, "deepl")
            return resp.json()

        try:
            data = with_retry(call, attempts=self.attempts, backoff=self.backoff)
        except EngineError as e:
            return [MtResult("", self.name, "deepl-v2", error=str(e)) for _ in reqs]
        translations = data.get("translations") or []
        if len(translations) != len(reqs):
            return [MtResult("", self.name, "deepl-v2", error="deepl: result count mismatch") for _ in reqs]
        out = []
        for r, t in zip(reqs, translations, strict=True):
            chars = len(tags.plain(r.source_tagged))
            usage = Usage(characters=chars, cost=estimate_cost(self.name, characters=chars))
            model = f"deepl-v2:{t.get('model_type_used', 'default')}"
            out.append(MtResult(from_xml(t.get("text", "")), self.name, model, usage))
        return out
