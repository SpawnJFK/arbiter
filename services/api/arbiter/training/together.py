"""Together AI fine-tuning (LoRA) over REST.

    POST /v1/files            multipart file=<jsonl>, purpose=fine-tune     -> {"id"}
    POST /v1/fine-tunes       {training_file, validation_file, model, lora, n_epochs, suffix}
    GET  /v1/fine-tunes/{id}  {"status", "output_name", "total_price"?, ...}

Inference: Together serves the LoRA output through its OpenAI-compatible endpoint
(https://api.together.xyz/v1) under `output_name`. Shapes follow the public API docs as
of Oct 2026 (no Context7 in the build session, see memory-bank/context7-log.md); verify
them against the docs with a small real job before the first customer job.
"""

from __future__ import annotations

from decimal import Decimal

import httpx

from arbiter.engines.http import check_response, with_retry
from arbiter.training.providers import ProviderJob, ProviderStatus

BASE = "https://api.together.xyz/v1"
_STATUS = {
    "pending": "running",
    "queued": "running",
    "running": "running",
    "compressing": "running",
    "uploading": "running",
    "completed": "succeeded",
    "error": "failed",
    "failed": "failed",
    "cancelled": "cancelled",
    "user_error": "failed",
}


class TogetherProvider:
    name = "together"
    inference_region = "us"

    def __init__(self, api_key: str, *, http_client: httpx.Client | None = None, n_epochs: int = 3) -> None:
        self.api_key = api_key
        self._http = http_client or httpx.Client(timeout=120.0)
        self.n_epochs = n_epochs

    def _h(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self.api_key}"}

    def _upload(self, data: bytes, filename: str) -> str:
        def call() -> str:
            resp = self._http.post(
                f"{BASE}/files",
                headers=self._h(),
                files={"file": (filename, data, "application/jsonl")},
                data={"purpose": "fine-tune"},
            )
            check_response(resp, "together")
            return str(resp.json()["id"])

        return with_retry(call, attempts=3, backoff=1.0)

    def start(self, train: bytes, validation: bytes, *, base_model: str, suffix: str) -> ProviderJob:
        train_id = self._upload(train, "train.jsonl")
        body: dict[str, object] = {
            "training_file": train_id,
            "model": base_model,
            "lora": True,
            "n_epochs": self.n_epochs,
            "suffix": suffix[:40],
        }
        if validation:
            body["validation_file"] = self._upload(validation, "validation.jsonl")
        resp = self._http.post(f"{BASE}/fine-tunes", headers=self._h(), json=body)
        check_response(resp, "together")
        data = resp.json()
        return ProviderJob(str(data["id"]), _STATUS.get(str(data.get("status", "pending")), "running"))  # type: ignore[arg-type]

    def poll(self, provider_job_id: str) -> ProviderStatus:
        resp = self._http.get(f"{BASE}/fine-tunes/{provider_job_id}", headers=self._h())
        check_response(resp, "together")
        data = resp.json()
        status = _STATUS.get(str(data.get("status", "")), "running")
        price = data.get("total_price")
        return ProviderStatus(
            status=status,  # type: ignore[arg-type]
            model_id=data.get("output_name") if status == "succeeded" else None,
            endpoint=BASE if status == "succeeded" else None,
            cost=Decimal(str(price)) if price is not None else None,
            error=str(data.get("error") or data.get("message") or "") or None if status == "failed" else None,
        )
