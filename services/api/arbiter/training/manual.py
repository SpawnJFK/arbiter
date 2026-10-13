"""Manual provider: no API call. The dataset is exported (GET /v1/training/jobs/{id}/dataset)
for an external trainer (own GPU box, a cloud the client prefers, an EU host); when the
model is served, its OpenAI-compatible endpoint is registered with POST /v1/custom-models
and evaluated like any other."""

from __future__ import annotations

from arbiter.training.providers import ProviderJob, ProviderStatus


class ManualProvider:
    name = "manual"
    inference_region = "global"  # declared per model at registration

    def start(self, train: bytes, validation: bytes, *, base_model: str, suffix: str) -> ProviderJob:
        return ProviderJob("manual", "manual")

    def poll(self, provider_job_id: str) -> ProviderStatus:
        return ProviderStatus("manual")
