"""Claude on Google Vertex AI (LlmClient). The second EU processing route (D-052).

Endpoint (Anthropic models on Vertex take the Messages API body through rawPredict):

    POST https://{host}/v1/projects/{project}/locations/{location}/publishers/anthropic/models/{model}:rawPredict

Host by location: "global" -> aiplatform.googleapis.com; the multi-regions "eu" and "us"
-> aiplatform.{location}.rep.googleapis.com; a single region such as europe-west4 ->
{location}-aiplatform.googleapis.com. Credential config `endpoint` overrides the host when
Google changes it. Default location is "eu", the EU multi-region.

Auth: a service account JSON key. We sign a JWT (RS256, pyjwt) with the account's private
key and exchange it at the token URI for an OAuth access token (grant type jwt-bearer),
cached until a minute before it expires. No Google SDK: two HTTP calls through httpx.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
import jwt

from arbiter.contracts import EngineError, Usage
from arbiter.engines.http import check_response, extract_json, with_retry
from arbiter.engines.pricing import estimate_cost

SCOPE = "https://www.googleapis.com/auth/cloud-platform"
DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"
VERTEX_VERSION = "vertex-2023-10-16"
JSON_ONLY = "\n\nRespond with a single JSON object only. No prose, no code fences."


def host_for(location: str) -> str:
    if location == "global":
        return "aiplatform.googleapis.com"
    if location in ("eu", "us"):
        return f"aiplatform.{location}.rep.googleapis.com"
    return f"{location}-aiplatform.googleapis.com"


def processing_region(location: str) -> str:
    if location == "eu" or location.startswith("europe-"):
        return "eu"
    if location == "us" or location.startswith("us-"):
        return "us"
    return "global"


class VertexClient:
    name = "vertex"

    def __init__(
        self,
        *,
        service_account: dict[str, Any] | str,
        project: str = "",
        location: str = "eu",
        model: str,
        endpoint: str = "",
        http_client: httpx.Client | None = None,
        attempts: int = 4,
        backoff: float = 1.0,
        timeout: float = 120.0,
    ) -> None:
        sa = json.loads(service_account) if isinstance(service_account, str) and service_account else {}
        self.sa: dict[str, Any] = service_account if isinstance(service_account, dict) else sa
        self.project = project or str(self.sa.get("project_id", ""))
        self.location = location or "eu"
        self.region = processing_region(self.location)
        self.model = model
        self.host = endpoint.removeprefix("https://").rstrip("/") if endpoint else host_for(self.location)
        self._http = http_client
        self.attempts = attempts
        self.backoff = backoff
        self.timeout = timeout
        self._token: str | None = None
        self._token_exp = 0.0

    def available(self) -> bool:
        return bool(
            self.sa.get("client_email") and self.sa.get("private_key") and self.project and self.model
        )

    @property
    def url(self) -> str:
        return (
            f"https://{self.host}/v1/projects/{self.project}/locations/{self.location}"
            f"/publishers/anthropic/models/{self.model}:rawPredict"
        )

    def _client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(timeout=self.timeout)
        return self._http

    def access_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_exp - 60:
            return self._token
        token_uri = str(self.sa.get("token_uri") or DEFAULT_TOKEN_URI)
        claims = {
            "iss": self.sa["client_email"],
            "sub": self.sa["client_email"],
            "scope": SCOPE,
            "aud": token_uri,
            "iat": int(now),
            "exp": int(now) + 3600,
        }
        headers = {"kid": self.sa["private_key_id"]} if self.sa.get("private_key_id") else None
        assertion = jwt.encode(claims, self.sa["private_key"], algorithm="RS256", headers=headers)
        resp = self._client().post(
            token_uri,
            data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
        )
        check_response(resp, "vertex-oauth")
        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise EngineError("vertex: token exchange returned no access_token")
        self._token = str(token)
        self._token_exp = now + float(data.get("expires_in", 3600))
        return self._token

    def complete_json(
        self,
        system: str,
        user: str,
        *,
        schema_hint: str = "",
        max_tokens: int = 2000,
        temperature: float = 0.0,
    ) -> tuple[dict[str, Any], Usage, str]:
        if not self.available():
            raise EngineError("vertex: service account, project or model not configured")
        sys_prompt = system + (f"\n\nJSON schema: {schema_hint}" if schema_hint else "") + JSON_ONLY
        body = {
            "anthropic_version": VERTEX_VERSION,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": sys_prompt,
            "messages": [{"role": "user", "content": user}],
        }
        usage_total = Usage()

        def call() -> tuple[dict[str, Any], str]:
            headers = {"authorization": f"Bearer {self.access_token()}", "content-type": "application/json"}
            resp = self._client().post(self.url, json=body, headers=headers)
            if resp.status_code == 401:  # token revoked or expired early: fetch a new one next try
                self._token = None
            check_response(resp, "vertex")
            data = resp.json()
            if data.get("type") == "error":
                raise EngineError(f"vertex: {data.get('error')}")
            u = data.get("usage") or {}
            usage_total.input_tokens += int(u.get("input_tokens", 0))
            usage_total.output_tokens += int(u.get("output_tokens", 0))
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            return extract_json(text), str(data.get("model") or self.model)

        parsed, model_version = with_retry(call, attempts=self.attempts, backoff=self.backoff)
        usage_total.cost = estimate_cost(
            "vertex",
            model=model_version,
            input_tokens=usage_total.input_tokens,
            output_tokens=usage_total.output_tokens,
        )
        return parsed, usage_total, f"vertex:{model_version}"
