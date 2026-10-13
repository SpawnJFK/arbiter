"""Fine-tuning providers behind one protocol.

    start(train_jsonl, validation_jsonl, base_model, suffix) -> ProviderJob
    poll(provider_job_id) -> ProviderStatus

Adapters: together.py and fireworks.py (their fine-tune REST APIs through httpx, LoRA),
manual.py (exports the dataset for an external trainer; the resulting endpoint is then
registered with POST /v1/custom-models). Tests use httpx.MockTransport; no adapter is
ever called for real from the test suite (the registry fence: settings.env == "test"
refuses to build a non-manual provider unless a transport is injected).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol

import httpx

from arbiter.config import Settings
from arbiter.contracts import EngineError
from arbiter.engines.credentials import ResolvedCredential

Status = Literal["running", "succeeded", "failed", "cancelled", "manual"]


@dataclass
class ProviderJob:
    id: str
    status: Status


@dataclass
class ProviderStatus:
    status: Status
    model_id: str | None = None  # name to send as "model" to the inference endpoint
    endpoint: str | None = None  # OpenAI-compatible base URL serving it
    cost: Decimal | None = None  # provider-reported cost, when it reports one
    error: str | None = None


class TrainingProvider(Protocol):
    name: str
    inference_region: str  # where the resulting endpoint processes data

    def start(self, train: bytes, validation: bytes, *, base_model: str, suffix: str) -> ProviderJob: ...

    def poll(self, provider_job_id: str) -> ProviderStatus: ...


def get_provider(
    name: str,
    cred: ResolvedCredential | None,
    settings: Settings,
    *,
    http_client: httpx.Client | None = None,
) -> TrainingProvider:
    if name == "manual":
        from arbiter.training.manual import ManualProvider

        return ManualProvider()
    if settings.is_test and http_client is None:
        raise EngineError(f"training provider {name!r} is not available in the test environment")
    if cred is None or not cred.secret:
        raise EngineError(f"training provider {name!r} is not configured (missing API key)")
    if name == "together":
        from arbiter.training.together import TogetherProvider

        return TogetherProvider(cred.secret, http_client=http_client)
    if name == "fireworks":
        from arbiter.training.fireworks import FireworksProvider

        account = str(cred.config.get("account_id") or settings.fireworks_account_id)
        if not account:
            raise EngineError("fireworks: account_id missing in the credential config")
        return FireworksProvider(cred.secret, account, http_client=http_client)
    raise EngineError(f"unknown training provider {name!r}")
