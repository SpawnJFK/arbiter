"""Fireworks AI supervised fine-tuning (LoRA) over REST.

    POST /v1/accounts/{acct}/datasets                         {datasetId, dataset: {exampleCount}}
    POST /v1/accounts/{acct}/datasets/{id}:upload             multipart file=<jsonl>
    POST /v1/accounts/{acct}/supervisedFineTuningJobs         {dataset, evaluationDataset, baseModel,
                                                               outputModel, epochs, loraRank}
    GET  /v1/accounts/{acct}/supervisedFineTuningJobs/{id}    {"state": "JOB_STATE_*", "outputModel"}

Inference: https://api.fireworks.ai/inference/v1 (OpenAI-compatible) with
model "accounts/{acct}/models/{id}" once the LoRA is deployed. Shapes follow the public
docs as of Oct 2026 without Context7; verify with a small real job before customer use.
"""

from __future__ import annotations

import re

import httpx

from arbiter.engines.http import check_response
from arbiter.models import new_id
from arbiter.training.providers import ProviderJob, ProviderStatus

BASE = "https://api.fireworks.ai/v1"
INFERENCE = "https://api.fireworks.ai/inference/v1"
_STATE = {
    "JOB_STATE_CREATING": "running",
    "JOB_STATE_PENDING": "running",
    "JOB_STATE_RUNNING": "running",
    "JOB_STATE_WRITING_RESULTS": "running",
    "JOB_STATE_VALIDATING": "running",
    "JOB_STATE_COMPLETED": "succeeded",
    "JOB_STATE_FAILED": "failed",
    "JOB_STATE_CANCELLED": "cancelled",
    "JOB_STATE_EXPIRED": "failed",
}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")[:60] or "arbiter"


class FireworksProvider:
    name = "fireworks"
    inference_region = "us"

    def __init__(
        self, api_key: str, account_id: str, *, http_client: httpx.Client | None = None, epochs: int = 3
    ) -> None:
        self.api_key = api_key
        self.account = account_id
        self._http = http_client or httpx.Client(timeout=120.0)
        self.epochs = epochs

    def _h(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self.api_key}"}

    def _dataset(self, data: bytes, dataset_id: str) -> str:
        count = data.count(b"\n")
        resp = self._http.post(
            f"{BASE}/accounts/{self.account}/datasets",
            headers=self._h(),
            json={"datasetId": dataset_id, "dataset": {"exampleCount": str(count)}},
        )
        check_response(resp, "fireworks")
        resp = self._http.post(
            f"{BASE}/accounts/{self.account}/datasets/{dataset_id}:upload",
            headers=self._h(),
            files={"file": (f"{dataset_id}.jsonl", data, "application/jsonl")},
        )
        check_response(resp, "fireworks")
        return f"accounts/{self.account}/datasets/{dataset_id}"

    def start(self, train: bytes, validation: bytes, *, base_model: str, suffix: str) -> ProviderJob:
        tag = _slug(f"{suffix}-{new_id('d')[-8:]}")
        body: dict[str, object] = {
            "dataset": self._dataset(train, f"{tag}-train"),
            "baseModel": base_model,
            "outputModel": f"accounts/{self.account}/models/{tag}",
            "epochs": self.epochs,
            "loraRank": 16,
        }
        if validation:
            body["evaluationDataset"] = self._dataset(validation, f"{tag}-val")
        resp = self._http.post(
            f"{BASE}/accounts/{self.account}/supervisedFineTuningJobs", headers=self._h(), json=body
        )
        check_response(resp, "fireworks")
        data = resp.json()
        job_id = str(data.get("name", "")).rsplit("/", 1)[-1]
        return ProviderJob(job_id, _STATE.get(str(data.get("state")), "running"))  # type: ignore[arg-type]

    def poll(self, provider_job_id: str) -> ProviderStatus:
        resp = self._http.get(
            f"{BASE}/accounts/{self.account}/supervisedFineTuningJobs/{provider_job_id}", headers=self._h()
        )
        check_response(resp, "fireworks")
        data = resp.json()
        status = _STATE.get(str(data.get("state")), "running")
        ok = status == "succeeded"
        return ProviderStatus(
            status=status,  # type: ignore[arg-type]
            model_id=str(data.get("outputModel")) if ok else None,
            endpoint=INFERENCE if ok else None,
            error=str((data.get("status") or {}).get("message") or "") or None
            if status == "failed"
            else None,
        )
