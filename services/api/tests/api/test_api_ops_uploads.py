"""Direct uploads (R-IN-03): create -> PUT bytes -> complete, local signed URL and S3 presign."""

from __future__ import annotations

from urllib.parse import urlsplit

import boto3
import pytest
from api_helpers import client, register
from moto import mock_aws
from test_api_cust_helpers import DOC, drain, project, quote

from arbiter import storage
from arbiter.config import Settings
from arbiter.models import Organization, UploadSession


def _create(c, h, name="notes.md", size=len(DOC), **extra):
    body = {"filename": name, "size": size, "content_type": "text/markdown", "source_lang": "en", **extra}
    return c.post("/v1/uploads", headers=h, json=body)


def _put(c, url: str, data: bytes, ct: str = "text/markdown"):
    parts = urlsplit(url)
    return c.put(f"{parts.path}?{parts.query}", content=data, headers={"Content-Type": ct})


def test_local_direct_upload_flow_then_quote(db):
    c = client()
    h = register(c)
    r = _create(c, h)
    assert r.status_code == 201, r.text
    up = r.json()
    assert up["method"] == "PUT" and up["backend"] == "local"
    assert up["max_bytes"] == 1024**3 and up["headers"] == {"Content-Type": "text/markdown"}
    assert up["upload_id"].startswith("upl_") and up["expires_at"]

    early = c.post(f"/v1/uploads/{up['upload_id']}/complete", headers=h)
    assert early.status_code == 409 and early.json()["error"]["code"] == "upload_missing"

    assert _put(c, up["url"], DOC).status_code == 204
    done = c.post(f"/v1/uploads/{up['upload_id']}/complete", headers=h)
    assert done.status_code == 201, done.text
    f = done.json()
    assert f["filename"] == "notes.md" and f["segment_count"] >= 4 and f["size"] == len(DOC)
    again = c.post(f"/v1/uploads/{up['upload_id']}/complete", headers=h)
    assert again.status_code == 201 and again.json()["id"] == f["id"]
    assert c.get(f"/v1/uploads/{up['upload_id']}", headers=h).json()["status"] == "completed"

    q = quote(c, h, f["id"])
    prj = project(c, h, q["id"], "auto")
    drain()
    job = c.get(f"/v1/jobs/{prj['jobs'][0]['id']}", headers=h).json()
    assert job["state"] == "delivered"
    # local backend streams the download (no redirect)
    dl = c.get(f"/v1/jobs/{job['id']}/download", headers=h)
    assert dl.status_code == 200 and dl.content


def test_upload_validation_and_signature(db):
    c = client()
    h = register(c)
    bad_ext = _create(c, h, name="scan.pdf")
    assert bad_ext.status_code == 422 and bad_ext.json()["error"]["code"] == "unsupported_file"
    assert _create(c, h, size=1024**3 + 1).status_code == 422
    assert _create(c, h, size=0).status_code == 422

    up = _create(c, h, size=10).json()
    parts = urlsplit(up["url"])
    forged = c.put(f"{parts.path}?expires=9999999999&token={'0' * 64}", content=b"x" * 10)
    assert forged.status_code == 403 and forged.json()["error"]["code"] == "invalid_signature"
    too_big = _put(c, up["url"], b"x" * 11)
    assert too_big.status_code == 413 and too_big.json()["error"]["code"] == "too_large"


def test_size_mismatch_rejects_and_deletes(db):
    c = client()
    h = register(c)
    up = _create(c, h, size=len(DOC) + 5).json()
    assert _put(c, up["url"], DOC).status_code == 204
    r = c.post(f"/v1/uploads/{up['upload_id']}/complete", headers=h)
    assert r.status_code == 422 and r.json()["error"]["code"] == "size_mismatch"
    u = db.get(UploadSession, up["upload_id"])
    db.refresh(u)
    assert u.status == "rejected" and not storage.exists(u.storage_key)


def test_damaged_file_rejected_on_complete(db):
    c = client()
    h = register(c)
    junk = b"PK\x03\x04 not really a zip"
    up = _create(c, h, name="broken.docx", size=len(junk)).json()
    assert _put(c, up["url"], junk, "application/octet-stream").status_code == 204
    r = c.post(f"/v1/uploads/{up['upload_id']}/complete", headers=h)
    assert r.status_code == 422 and r.json()["error"]["code"] == "unsupported_file"


def test_tenancy_idempotency_and_module_gate(db):
    c = client()
    h1 = register(c)
    h2 = register(c, email="other@example.com", org="Other Ltd")
    up = _create(c, h1).json()
    assert c.post(f"/v1/uploads/{up['upload_id']}/complete", headers=h2).status_code == 404
    assert c.get(f"/v1/uploads/{up['upload_id']}", headers=h2).status_code == 404

    body = {"filename": "a.md", "size": 3, "content_type": "text/markdown", "source_lang": "en"}
    k = {"Idempotency-Key": "same-key-1"}
    a = c.post("/v1/uploads", headers={**h1, **k}, json=body).json()
    b = c.post("/v1/uploads", headers={**h1, **k}, json=body).json()
    assert a["upload_id"] == b["upload_id"]

    org = db.query(Organization).filter(Organization.name == "Other Ltd").one()
    org.settings = {"modules": ["engine"]}
    db.commit()
    r = _create(c, h2)
    assert r.status_code == 404 and r.json()["error"]["code"] == "module_disabled"


@pytest.fixture
def s3_backend():
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="arbiter-test")
        backend = storage.S3Storage(
            Settings(
                env="test",
                storage_backend="s3",
                s3_bucket="arbiter-test",
                s3_region="us-east-1",
                s3_access_key_id="test",
                s3_secret_access_key="test",
            )
        )
        storage.use(backend)
        try:
            yield backend
        finally:
            storage.use(None)


def test_s3_direct_upload_and_presigned_download(db, s3_backend):
    c = client()
    c.follow_redirects = False
    h = register(c)
    up = _create(c, h).json()
    assert up["backend"] == "s3" and "X-Amz-Signature=" in up["url"]
    assert c.put(urlsplit(up["url"]).path).status_code in (404, 405)  # nothing on the API side
    session = db.get(UploadSession, up["upload_id"])
    s3_backend.put(session.storage_key, DOC)  # what the browser's presigned PUT does
    f = c.post(f"/v1/uploads/{up['upload_id']}/complete", headers=h).json()
    q = quote(c, h, f["id"])
    job_id = project(c, h, q["id"], "auto")["jobs"][0]["id"]
    drain()
    dl = c.get(f"/v1/jobs/{job_id}/download", headers=h)
    assert dl.status_code == 302 and dl.headers["cache-control"] == "no-store"
    loc = dl.headers["location"]
    assert "/arbiter-test/" in loc and "X-Amz-Signature=" in loc and "notes.sr.md" in loc
    ev = c.get(f"/v1/jobs/{job_id}/evidence?format=pdf", headers=h)
    assert ev.status_code == 302 and "evidence.pdf" in ev.headers["location"]
    blob = c.put(f"/v1/uploads/{up['upload_id']}/blob?expires=1&token={'0' * 32}", content=b"x")
    assert blob.status_code == 404  # the signed local endpoint does not exist with s3


SRT = b"1\n00:00:01,000 --> 00:00:03,000\nHello there, this is a subtitle line.\n\n2\n00:00:04,000 --> 00:00:06,000\nA second cue.\n"


def test_handler_options_travel_from_upload_to_extract_and_merge(db):
    """D-076: options given at upload are validated early, stored on the file and used again
    by quote, extraction and merge."""
    c = client()
    h = register(c)
    bad = _create(c, h, name="clip.srt", size=len(SRT), options={"max_chars_per_line": "x"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "unsupported_file"
    wrong = _create(c, h, options={"max_chars_per_line": 80})  # markdown takes no options
    assert wrong.status_code == 422
    r = _create(c, h, name="clip.srt", size=len(SRT), options={"max_chars_per_line": 80})
    assert r.status_code == 201, r.text
    up = r.json()
    assert _put(c, up["url"], SRT, ct="text/markdown").status_code == 204
    done = c.post(f"/v1/uploads/{up['upload_id']}/complete", headers=h)
    assert done.status_code == 201, done.text
    f = done.json()
    assert f["options"] == {"max_chars_per_line": 80} and f["format"] == "srt"
    from arbiter.models import FileAsset, Segment

    assert db.get(FileAsset, f["id"]).options == {"max_chars_per_line": 80}
    q = quote(c, h, f["id"])
    prj = project(c, h, q["id"], "auto")
    drain()
    job = c.get(f"/v1/jobs/{prj['jobs'][0]['id']}", headers=h).json()
    assert job["state"] == "delivered"
    from sqlalchemy import select

    segs = db.execute(select(Segment).where(Segment.job_id == job["id"])).scalars().all()
    assert segs and all(s.max_length == 80 for s in segs if s.max_length is not None)
    assert any(s.max_length == 80 for s in segs)
    dl = c.get(f"/v1/jobs/{job['id']}/download", headers=h)
    assert dl.status_code == 200 and b"-->" in dl.content

    # multipart POST /files takes the same options as a JSON form field
    m = c.post(
        "/v1/files",
        headers=h,
        files={"file": ("clip2.srt", SRT, "application/x-subrip")},
        data={"source_lang": "en", "options": '{"max_chars_per_line": 40}'},
    )
    assert m.status_code == 201, m.text
    assert m.json()["options"] == {"max_chars_per_line": 40}
    bad_json = c.post(
        "/v1/files",
        headers=h,
        files={"file": ("clip3.srt", SRT, "application/x-subrip")},
        data={"source_lang": "en", "options": "[1, 2]"},
    )
    assert bad_json.status_code == 422
