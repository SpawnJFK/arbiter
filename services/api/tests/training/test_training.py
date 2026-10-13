"""Own models (D-054): dataset export with consent, providers (mocked), evaluation onto the
scoreboard, activation, EU rules and the API."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from train_helpers import org_with_segments

from arbiter import storage
from arbiter.config import get_settings
from arbiter.engines import routing
from arbiter.engines.mock import MockLlm
from arbiter.engines.openai_compatible import CustomModelMt, OpenAiCompatibleClient
from arbiter.errors import Invalid
from arbiter.models import CustomModel, EngineScore, Organization, TrainingJob, WorkItem
from arbiter.pipeline import worker
from arbiter.training import dataset, service
from arbiter.training.fireworks import FireworksProvider
from arbiter.training.together import TogetherProvider

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))


@pytest.fixture(autouse=True)
def small_minimum(monkeypatch):
    monkeypatch.setattr(get_settings(), "training_min_examples", 5)
    monkeypatch.setattr(get_settings(), "custom_model_min_eval_segments", 2)


def echo_engine(name: str) -> CustomModelMt:
    """A fine-tuned model behind a stubbed OpenAI-compatible endpoint: answers with a correct
    Serbian-looking translation in the training format."""

    def handler(req: httpx.Request) -> httpx.Response:
        user = json.loads(req.content)["messages"][1]["content"]
        out = user.replace("Open", "Otvori").replace("item", "stavku").replace("now", "sada")
        return httpx.Response(200, json={"choices": [{"message": {"content": out}}], "usage": {}})

    client = OpenAiCompatibleClient(
        name=name,
        base_url="https://ft.example.com/v1",
        api_key="k",
        model="ft",
        json_mode=False,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        backoff=0,
    )
    return CustomModelMt(client, name=name)


# ------------------------------------------------------------------ dataset


def test_dataset_needs_consent(db):
    org = org_with_segments(db, consent=False)
    with pytest.raises(dataset.ConsentRequired):
        dataset.build(db, org, "en", "sr")
    stats = service.preview(db, org, "en", "sr", "general")  # preview counts without consent
    assert stats["consent"] is False and stats["examples"] == 30


def test_dataset_only_human_approved_deduped_split_and_tag_form(db):
    org = org_with_segments(db, n=40)
    ds = dataset.build(db, org, "en", "sr")
    assert ds.stats["candidates"] == 41  # 40 + the duplicate; auto-approved and open never qualify
    assert ds.stats["dropped"]["duplicate"] == 1
    assert ds.stats["examples"] == 40 and ds.stats["validation"] >= 1
    assert ds.stats["train"] + ds.stats["validation"] == 40
    sources = {e.source for e in ds.train + ds.validation}
    assert all("<g1>" in s and "⟦" not in s for s in sources)
    # deterministic split: same answer twice, never overlapping
    again = dataset.build(db, org, "en", "sr")
    assert {e.source for e in again.validation} == {e.source for e in ds.validation}
    assert not {e.source for e in ds.train} & {e.source for e in ds.validation}
    lines = dataset.to_jsonl(ds.train, "en", "sr").decode().splitlines()
    row = json.loads(lines[0])
    assert [m["role"] for m in row["messages"]] == ["system", "user", "assistant"]
    assert row["messages"][2]["content"].startswith("Otvori <g1>")


def test_dataset_respects_pair_and_domain(db):
    org = org_with_segments(db, n=10, content_type="legal")
    assert dataset.build(db, org, "en", "sr", "legal").stats["examples"] == 10
    assert dataset.build(db, org, "en", "sr", "medical").stats["examples"] == 0
    assert dataset.build(db, org, "en", "sr", "any").stats["examples"] == 10
    assert dataset.build(db, org, "en", "de", "legal").stats["examples"] == 0
    other = org_with_segments(db, n=3, slug="other")
    assert dataset.build(db, other, "en", "sr").stats["examples"] == 3  # never another org's data


# ------------------------------------------------------------------ manual provider -> register -> evaluate


def test_manual_job_register_evaluate_scoreboard_activate(db):
    org = org_with_segments(db, n=40)
    job = service.start_job(
        db,
        org,
        source_lang="en",
        target_lang="sr",
        domain="general",
        provider="manual",
        base_model="open-model-8b",
        actor=None,
    )
    assert job.state == "exported" and job.dataset_stats["train"] >= 5
    assert storage.get(job.train_storage_key).count(b"\n") == job.dataset_stats["train"]
    model = service.register_model(
        db,
        org,
        name="EN-SR general v1",
        source_lang="en",
        target_lang="sr",
        domain="general",
        endpoint="https://ft.example.com/v1",
        provider_model_id="ft",
        credential_id=None,
        region="global",
        training_job_id=job.id,
    )
    assert job.state == "evaluating" and job.custom_model_id == model.id
    assert db.execute(select(WorkItem).where(WorkItem.kind == "training.evaluate")).scalar_one()
    service.evaluate(db, job.id, engine=echo_engine(model.engine_name), judge=MockLlm())
    assert job.state == "ready"
    score = db.execute(select(EngineScore).where(EngineScore.engine == model.engine_name)).scalar_one()
    assert score.segments_measured == job.dataset_stats["validation"]
    assert score.mean_qe > 90 and score.mean_edit_distance < 0.2
    assert model.eval_segments == score.segments_measured and not model.active
    # the scoreboard ranks the custom model once it is available (active) for the org
    service.set_active(db, org, model.id, True)
    choice = routing.choose(
        db,
        org=org,
        purpose="mt",
        source_lang="en",
        target_lang="sr",
        content_type="general",
        available=["mock-mt", model.engine_name],
        region_lookup=lambda n: "local" if n == "mock-mt" else "global",
    )
    assert choice.engines[0] == model.engine_name and choice.source == "scoreboard"
    # the same model never helps an EU org (its endpoint is not EU)
    org.settings = {**org.settings, "processing_region": "eu"}
    choice = routing.choose(
        db,
        org=org,
        purpose="mt",
        source_lang="en",
        target_lang="sr",
        available=["mock-mt", model.engine_name],
        region_lookup=lambda n: "local" if n == "mock-mt" else "global",
    )
    assert choice.engines == ["mock-mt"]


def test_failing_model_scores_zero_not_skipped(db):
    org = org_with_segments(db, n=40)
    job = service.start_job(
        db,
        org,
        source_lang="en",
        target_lang="sr",
        domain="general",
        provider="manual",
        base_model="m",
        actor=None,
    )
    model = service.register_model(
        db,
        org,
        name="broken",
        source_lang="en",
        target_lang="sr",
        domain="general",
        endpoint="https://ft.example.com/v1",
        provider_model_id="x",
        credential_id=None,
        region="global",
        training_job_id=job.id,
    )
    down = OpenAiCompatibleClient(
        name=model.engine_name,
        base_url="https://ft.example.com/v1",
        api_key="",
        model="x",
        http_client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(400))),
        backoff=0,
    )
    service.evaluate(db, job.id, engine=CustomModelMt(down, name=model.engine_name), judge=MockLlm())
    assert model.eval_mean_qe == 0.0 and job.dataset_stats["eval"]["failures"] == model.eval_segments


def test_not_enough_examples_and_unknown_provider(db):
    org = org_with_segments(db, n=3)
    with pytest.raises(Invalid, match="not enough"):
        service.start_job(
            db,
            org,
            source_lang="en",
            target_lang="sr",
            domain="general",
            provider="manual",
            base_model="m",
            actor=None,
        )
    with pytest.raises(Invalid):
        service.start_job(
            db,
            org,
            source_lang="en",
            target_lang="sr",
            domain="general",
            provider="nope",
            base_model="m",
            actor=None,
        )
    # a real provider without a key (and without a stub in tests) is refused
    with pytest.raises(Invalid):
        service.start_job(
            db,
            org,
            source_lang="en",
            target_lang="sr",
            domain="general",
            provider="together",
            base_model="m",
            actor=None,
        )


def test_eu_org_must_train_manually_and_evaluate_only_eu_models(db):
    org = org_with_segments(db, n=40, region="eu")
    from arbiter import crypto
    from arbiter.models import EngineCredential

    db.add(
        EngineCredential(
            scope="org",
            org_id=org.id,
            provider="together",
            label="t",
            secret_encrypted=crypto.encrypt("tg-key"),
            secret_hint="...-key",
            config={},
        )
    )
    db.flush()
    transport = httpx.MockTransport(lambda r: httpx.Response(500))
    with pytest.raises(Invalid, match="EU processing"):
        service.start_job(
            db,
            org,
            source_lang="en",
            target_lang="sr",
            domain="general",
            provider="together",
            base_model="m",
            actor=None,
            http_client=httpx.Client(transport=transport),
        )
    job = service.start_job(
        db,
        org,
        source_lang="en",
        target_lang="sr",
        domain="general",
        provider="manual",
        base_model="m",
        actor=None,
    )
    service.register_model(
        db,
        org,
        name="US hosted",
        source_lang="en",
        target_lang="sr",
        domain="general",
        endpoint="https://ft.example.com/v1",
        provider_model_id="x",
        credential_id=None,
        region="us",
        training_job_id=job.id,
    )
    service.evaluate(db, job.id, engine=echo_engine("custom:x"), judge=MockLlm())
    assert job.state == "failed" and "EU" in job.error


# ------------------------------------------------------------------ Together / Fireworks (stubbed)


def test_together_job_polls_to_success_then_evaluates(db):
    org = org_with_segments(db, n=40)
    from arbiter import crypto
    from arbiter.models import EngineCredential

    db.add(
        EngineCredential(
            scope="platform",
            provider="together",
            label="t",
            secret_encrypted=crypto.encrypt("tg-key"),
            secret_hint="...-key",
            config={},
        )
    )
    db.flush()
    state = {"polls": 0, "uploads": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["authorization"] == "Bearer tg-key"
        if req.url.path == "/v1/files":
            state["uploads"] += 1
            assert b"fine-tune" in req.content
            return httpx.Response(200, json={"id": f"file-{state['uploads']}"})
        if req.method == "POST" and req.url.path == "/v1/fine-tunes":
            body = json.loads(req.content)
            assert body["lora"] is True and body["training_file"] == "file-1"
            assert body["validation_file"] == "file-2" and body["model"] == "base/llama"
            return httpx.Response(200, json={"id": "ft-123", "status": "pending"})
        assert req.url.path == "/v1/fine-tunes/ft-123"
        state["polls"] += 1
        if state["polls"] == 1:
            return httpx.Response(200, json={"id": "ft-123", "status": "running"})
        return httpx.Response(
            200,
            json={"id": "ft-123", "status": "completed", "output_name": "acct/llama-ft", "total_price": 4.2},
        )

    http = httpx.Client(transport=httpx.MockTransport(handler))
    job = service.start_job(
        db,
        org,
        source_lang="en",
        target_lang="sr",
        domain="general",
        provider="together",
        base_model="base/llama",
        actor=None,
        http_client=http,
    )
    assert job.state == "running" and job.provider_job_id == "ft-123"
    assert db.execute(select(WorkItem).where(WorkItem.kind == "training.poll")).scalar_one()
    service.refresh(db, job.id, http_client=http)
    assert job.state == "running" and job.polls == 1
    service.refresh(db, job.id, http_client=http)
    assert job.state == "evaluating" and str(job.cost) == "4.2"
    model = db.get(CustomModel, job.custom_model_id)
    assert model.provider_model_id == "acct/llama-ft" and model.endpoint == "https://api.together.xyz/v1"
    assert model.region == "us" and model.credential_id is not None and not model.active


def test_together_failure_marks_job_failed(db):
    p = TogetherProvider(
        "k",
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json={"status": "error", "message": "bad data"})
            )
        ),
    )
    st = p.poll("ft-1")
    assert st.status == "failed" and st.error == "bad data"


def test_fireworks_start_and_poll():
    calls: list[tuple[str, str]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.method, req.url.path))
        if req.url.path.endswith("/supervisedFineTuningJobs"):
            body = json.loads(req.content)
            assert body["baseModel"] == "accounts/fireworks/models/llama"
            assert body["dataset"].startswith("accounts/acct/datasets/")
            return httpx.Response(
                200, json={"name": "accounts/acct/supervisedFineTuningJobs/j1", "state": "JOB_STATE_CREATING"}
            )
        if req.url.path.endswith("/supervisedFineTuningJobs/j1"):
            return httpx.Response(
                200, json={"state": "JOB_STATE_COMPLETED", "outputModel": "accounts/acct/models/m1"}
            )
        return httpx.Response(200, json={})

    p = FireworksProvider("k", "acct", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    job = p.start(
        b'{"messages": []}\n',
        b'{"messages": []}\n',
        base_model="accounts/fireworks/models/llama",
        suffix="Acme en-sr",
    )
    assert job.id == "j1" and job.status == "running"
    assert sum(1 for m, path in calls if path.endswith(":upload")) == 2
    st = p.poll("j1")
    assert st.status == "succeeded" and st.model_id == "accounts/acct/models/m1"
    assert st.endpoint == "https://api.fireworks.ai/inference/v1"


def test_worker_knows_training_steps_and_fails_dead_items(db):
    assert worker._handler("training.poll") is not None
    assert worker._handler("training.evaluate") is not None
    org = org_with_segments(db, n=40)
    job = service.start_job(
        db,
        org,
        source_lang="en",
        target_lang="sr",
        domain="general",
        provider="manual",
        base_model="m",
        actor=None,
    )
    service.fail(db, job.id, "provider gone")
    assert job.state == "failed" and job.error == "provider gone"


# ------------------------------------------------------------------ API


def test_training_api_flow(db):
    from api_helpers import client, register

    c = client()
    h = register(c)
    org = db.execute(select(Organization)).scalar_one()
    org_with_segments(db, n=40, org=org)
    db.commit()
    r = c.post("/v1/training/datasets/preview", headers=h, json={"source_lang": "en", "target_lang": "sr"})
    assert r.status_code == 200 and r.json()["examples"] == 40 and r.json()["consent"] is False
    assert r.json()["estimated_cost"]["manual"] == "0.00"
    body = {"source_lang": "en", "target_lang": "sr", "provider": "manual", "base_model": "open-8b"}
    r = c.post("/v1/training/jobs", headers=h, json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "training_consent_required"
    assert c.patch("/v1/org", headers=h, json={"training_consent": True}).status_code == 200
    r = c.post("/v1/training/jobs", headers=h, json=body)
    assert r.status_code == 201, r.text
    jid = r.json()["id"]
    assert r.json()["state"] == "exported"
    assert [j["id"] for j in c.get("/v1/training/jobs", headers=h).json()["items"]] == [jid]
    r = c.get(f"/v1/training/jobs/{jid}/dataset?split=validation", headers=h)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/jsonl")
    assert c.post(f"/v1/training/jobs/{jid}/refresh", headers=h).json()["state"] == "exported"
    r = c.post(
        "/v1/custom-models",
        headers=h,
        json={
            "name": "EN-SR v1",
            "source_lang": "en",
            "target_lang": "sr",
            "endpoint": "https://ft.example.com/v1",
            "provider_model_id": "ft",
            "region": "eu",
            "training_job_id": jid,
        },
    )
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    assert r.json()["engine"] == f"custom:{mid}" and r.json()["active"] is False
    assert c.get(f"/v1/training/jobs/{jid}", headers=h).json()["state"] == "evaluating"
    assert c.post(f"/v1/custom-models/{mid}/activate", headers=h).json()["active"] is True
    items = c.get("/v1/custom-models", headers=h).json()["items"]
    assert items[0]["id"] == mid and items[0]["scoreboard"] is None
    assert c.post(f"/v1/custom-models/{mid}/deactivate", headers=h).json()["active"] is False
    # tenancy
    h2 = register(c, email="o2@example.com", org="O2")
    assert c.get(f"/v1/training/jobs/{jid}", headers=h2).status_code == 404
    assert c.post(f"/v1/custom-models/{mid}/activate", headers=h2).status_code == 404
    # job rows belong to the org
    assert db.get(TrainingJob, jid).org_id == org.id
