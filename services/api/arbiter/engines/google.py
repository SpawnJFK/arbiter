"""Google Cloud Translation, Basic edition, via API key (MtEngine).

Only active when ARBITER_GOOGLE_API_KEY is set. API-key authentication is supported by
the Basic edition REST endpoint (``/language/translate/v2``); the Advanced v3 endpoint
needs OAuth service-account credentials, which this deployment does not hold. If v3
features (glossaries, custom models) are needed later, add a service-account client
rather than stretching this one.

Tags are protected as HTML (``format=html``): paired codes become
``<span id="a1">…</span>`` (Google moves spans with their words), standalone codes become
``<span translate="no" id="s2"></span>``. Non-nested sources fall back to standalone spans
for open/close (ids ``o1``/``c1``). No glossary support in Basic: ``supports_glossary``
is False and term adherence is enforced by the hard checks.
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

API_URL = "https://translation.googleapis.com/language/translate/v2"
BATCH = 100  # Basic edition: up to 128 q values per request


def to_html(tagged: str) -> str:
    paired = tags.is_balanced_tagged(tagged)
    out: list[str] = []
    for kind, value in tags.pieces(tagged):
        if kind == "text":
            assert isinstance(value, str)
            out.append(html.escape(value, quote=False))
            continue
        assert isinstance(value, tuple)
        cid, ckind = value
        a = html.escape(cid, quote=True)
        if ckind == "standalone":
            out.append(f'<span translate="no" id="s{a}"></span>')
        elif paired:
            out.append(f'<span id="a{a}">' if ckind == "open" else "</span>")
        else:
            prefix = "o" if ckind == "open" else "c"
            out.append(f'<span translate="no" id="{prefix}{a}"></span>')
    return "".join(out)


_SPAN_OPEN_RE = re.compile(r'<span\b[^>]*\bid="([asoc])([^"]*)"[^>]*>(</span>)?|</span>')


def from_html(text: str) -> str:
    out: list[str] = []
    stack: list[str] = []
    pos = 0
    for m in _SPAN_OPEN_RE.finditer(text):
        out.append(tags.escape_text(html.unescape(text[pos : m.start()])))
        pos = m.end()
        if m.group(1) is None:  # bare </span> closes a paired code
            out.append(f"⟦/{stack.pop()}⟧" if stack else "")
            continue
        kind, cid = m.group(1), html.unescape(m.group(2))
        if kind == "a":
            stack.append(cid)
            out.append(f"⟦{cid}⟧")
            if m.group(3):  # Google collapsed an empty pair: <span id="a1"></span>
                out.append(f"⟦/{stack.pop()}⟧")
        elif kind == "s":
            out.append(f"⟦{cid}/⟧")
        elif kind == "o":
            out.append(f"⟦{cid}⟧")
        else:
            out.append(f"⟦/{cid}⟧")
    out.append(tags.escape_text(html.unescape(text[pos:])))
    return "".join(out)


class GoogleEngine:
    name = "google"
    supports_glossary = False

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        api_key: str | None = None,
        http_client: httpx.Client | None = None,
        attempts: int = 4,
        backoff: float = 1.0,
        timeout: float = 60.0,
    ) -> None:
        s = settings or get_settings()
        self.api_key = s.google_api_key if api_key is None else api_key
        self._http = http_client
        self.attempts = attempts
        self.backoff = backoff
        self.timeout = timeout

    def available(self) -> bool:
        return bool(self.api_key)

    def _client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(timeout=self.timeout)
        return self._http

    def translate(self, requests: list[MtRequest]) -> list[MtResult]:
        if not self.available():
            raise EngineError("google: no API key configured")
        results: list[MtResult | None] = [None] * len(requests)
        groups: dict[tuple[str, str], list[int]] = {}
        for i, r in enumerate(requests):
            groups.setdefault((r.source_lang, r.target_lang), []).append(i)
        for (src, tgt), idxs in groups.items():
            for start in range(0, len(idxs), BATCH):
                chunk = idxs[start : start + BATCH]
                for i, res in zip(chunk, self._chunk([requests[i] for i in chunk], src, tgt), strict=True):
                    results[i] = res
        return [r for r in results if r is not None]

    def _chunk(self, reqs: list[MtRequest], src: str, tgt: str) -> list[MtResult]:
        body = {"q": [to_html(r.source_tagged) for r in reqs], "source": src, "target": tgt, "format": "html"}

        def call() -> dict:
            # The key travels as a header, not in the URL, so it never lands in access logs.
            resp = self._client().post(API_URL, json=body, headers={"x-goog-api-key": self.api_key})
            check_response(resp, "google")
            return resp.json()

        try:
            data = with_retry(call, attempts=self.attempts, backoff=self.backoff)
        except EngineError as e:
            return [MtResult("", self.name, "google-v2", error=str(e)) for _ in reqs]
        translations = (data.get("data") or {}).get("translations") or []
        if len(translations) != len(reqs):
            return [MtResult("", self.name, "google-v2", error="google: result count mismatch") for _ in reqs]
        out = []
        for r, t in zip(reqs, translations, strict=True):
            chars = len(tags.plain(r.source_tagged))
            usage = Usage(characters=chars, cost=estimate_cost(self.name, characters=chars))
            model = f"google-v2:{t.get('model', 'nmt')}"
            out.append(MtResult(from_html(t.get("translatedText", "")), self.name, model, usage))
        return out
