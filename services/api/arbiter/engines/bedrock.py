"""Claude through AWS Bedrock, Converse API (LlmClient). The EU processing route (D-052).

Model id and AWS region come from the engine credential config (or the ARBITER_BEDROCK_*
settings). For EU processing the model id is an EU geographic inference profile, e.g.
``eu.anthropic.claude-opus-5``: Bedrock then routes the request only among EU regions.
`region` (where data is processed) is derived from that id, never assumed:

    eu.<model>        -> "eu"      (EU geographic inference profile)
    global.<model>    -> "global"
    us./apac./...     -> "us" / "global"
    no profile prefix -> from the AWS region: eu-* -> "eu", us-* -> "us", else "global"

Retries: botocore's own retries are switched off (max_attempts=1) and the shared
`with_retry` policy handles throttling / 5xx / model-not-ready, like every other provider.
JSON-only, same as anthropic.py: a reply that is not a JSON object is retried once.
"""

from __future__ import annotations

from typing import Any

from arbiter.contracts import EngineError, Usage
from arbiter.engines.http import RetryableError, extract_json, with_retry
from arbiter.engines.pricing import estimate_cost

JSON_ONLY = "\n\nRespond with a single JSON object only. No prose, no code fences."
RETRYABLE_CODES = {
    "ThrottlingException",
    "ServiceUnavailableException",
    "InternalServerException",
    "ModelNotReadyException",
    "ModelTimeoutException",
}
_PROFILE_PREFIXES = {"eu": "eu", "global": "global", "us": "us", "us-gov": "us"}


def processing_region(model_id: str, aws_region: str) -> str:
    prefix = model_id.split(".", 1)[0] if "." in model_id else ""
    if prefix in _PROFILE_PREFIXES:
        return _PROFILE_PREFIXES[prefix]
    if prefix in ("apac", "jp", "au", "ca"):
        return "global"
    if aws_region.startswith("eu-"):
        return "eu"
    if aws_region.startswith("us-"):
        return "us"
    return "global"


class BedrockClient:
    name = "bedrock"

    def __init__(
        self,
        *,
        model: str,
        aws_region: str,
        access_key_id: str = "",
        secret_access_key: str = "",
        session_token: str = "",
        client: Any | None = None,
        attempts: int = 4,
        backoff: float = 1.0,
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self.aws_region = aws_region
        self.region = processing_region(model, aws_region)
        self._creds = (access_key_id, secret_access_key, session_token)
        self._client_obj = client
        self.attempts = attempts
        self.backoff = backoff
        self.timeout = timeout

    def available(self) -> bool:
        return self._client_obj is not None or bool(self._creds[0] and self._creds[1] and self.model)

    def _client(self) -> Any:
        if self._client_obj is None:
            import boto3
            from botocore.config import Config

            key_id, secret, token = self._creds
            self._client_obj = boto3.client(
                "bedrock-runtime",
                region_name=self.aws_region,
                aws_access_key_id=key_id,
                aws_secret_access_key=secret,
                aws_session_token=token or None,
                config=Config(
                    retries={"max_attempts": 1, "mode": "standard"},
                    read_timeout=self.timeout,
                    connect_timeout=10,
                ),
            )
        return self._client_obj

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
            raise EngineError("bedrock: no AWS credentials configured")
        from botocore.exceptions import BotoCoreError, ClientError

        sys_prompt = system + (f"\n\nJSON schema: {schema_hint}" if schema_hint else "") + JSON_ONLY
        request = {
            "modelId": self.model,
            "system": [{"text": sys_prompt}],
            "messages": [{"role": "user", "content": [{"text": user}]}],
            "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature},
        }
        usage_total = Usage()

        def call() -> dict[str, Any]:
            try:
                data = self._client().converse(**request)
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code", "")
                msg = e.response.get("Error", {}).get("Message", "")[:300]
                if code in RETRYABLE_CODES:
                    raise RetryableError(f"bedrock: {code}: {msg}") from e
                raise EngineError(f"bedrock: {code}: {msg}") from e
            except BotoCoreError as e:  # connection / endpoint errors
                raise RetryableError(f"bedrock: {type(e).__name__}: {e}") from e
            u = data.get("usage") or {}
            usage_total.input_tokens += int(u.get("inputTokens", 0))
            usage_total.output_tokens += int(u.get("outputTokens", 0))
            content = ((data.get("output") or {}).get("message") or {}).get("content") or []
            text = "".join(b.get("text", "") for b in content if isinstance(b, dict))
            return extract_json(text)

        parsed = with_retry(call, attempts=self.attempts, backoff=self.backoff)
        usage_total.cost = estimate_cost(
            "bedrock",
            model=self.model,
            input_tokens=usage_total.input_tokens,
            output_tokens=usage_total.output_tokens,
        )
        return parsed, usage_total, f"bedrock:{self.model}"
