"""Storage backends: local and S3 (moto, no network), presigned URLs, signed local uploads."""

from __future__ import annotations

import time
from urllib.parse import parse_qs, urlsplit

import boto3
import pytest
from moto import mock_aws

from arbiter import storage
from arbiter.config import Settings


def _s3_settings(**kw) -> Settings:
    base = dict(
        env="test",
        storage_backend="s3",
        s3_bucket="arbiter-test",
        s3_region="us-east-1",
        s3_access_key_id="test",
        s3_secret_access_key="test",
        s3_path_style=True,
    )
    base.update(kw)
    return Settings(**base)


@pytest.fixture
def s3():
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="arbiter-test")
        backend = storage.S3Storage(_s3_settings())
        storage.use(backend)
        try:
            yield backend
        finally:
            storage.use(None)


def test_local_roundtrip_size_and_key_safety(tmp_path):
    s = storage.LocalStorage(Settings(env="test", storage_dir=str(tmp_path)))
    key = storage.make_key("org_1", "source", "fil_1", "../../etc/passwd")
    assert ".." not in key and key.startswith("org_1/source/fil_1/")
    s.put(key, b"hello")
    assert s.get(key) == b"hello" and s.size(key) == 5
    s.delete(key)
    assert s.size(key) is None
    with pytest.raises(FileNotFoundError):
        s.get(key)
    with pytest.raises(ValueError):
        s.path("../outside")
    assert s.presign_get(key, filename="x.md", content_type="text/markdown", ttl=60) is None


def test_local_presign_put_is_signed_and_expires(tmp_path):
    settings = Settings(env="test", storage_dir=str(tmp_path), public_base_url="https://api.example.com")
    s = storage.LocalStorage(settings)
    req = s.presign_put("k", upload_id="upl_1", content_type="text/markdown", ttl=600)
    parts = urlsplit(req.url)
    assert req.method == "PUT" and req.headers == {"Content-Type": "text/markdown"}
    assert parts.netloc == "api.example.com" and parts.path == "/v1/uploads/upl_1/blob"
    q = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert storage.check_blob_token("upl_1", int(q["expires"]), q["token"], settings.jwt_secret)
    assert not storage.check_blob_token("upl_2", int(q["expires"]), q["token"], settings.jwt_secret)
    assert not storage.check_blob_token("upl_1", int(q["expires"]) + 1, q["token"], settings.jwt_secret)
    assert not storage.check_blob_token(
        "upl_1", int(q["expires"]), q["token"], settings.jwt_secret, now=time.time() + 3600
    )


def test_s3_roundtrip_and_missing(s3):
    s3.put("org/source/fil/a.md", b"# hi")
    assert storage.get("org/source/fil/a.md") == b"# hi"
    assert storage.size("org/source/fil/a.md") == 4 and storage.exists("org/source/fil/a.md")
    assert storage.size("org/nope") is None
    with pytest.raises(FileNotFoundError):
        storage.get("org/nope")
    storage.delete("org/source/fil/a.md")
    assert not storage.exists("org/source/fil/a.md")


def test_s3_presigned_urls_carry_signature_type_and_disposition(s3):
    put = storage.presign_put("org/source/upl/a.md", upload_id="upl", content_type="text/markdown", ttl=900)
    assert put.method == "PUT" and put.headers["Content-Type"] == "text/markdown"
    q = parse_qs(urlsplit(put.url).query)
    assert "/arbiter-test/org/source/upl/a.md" in put.url  # path-style addressing
    assert q["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"] and q["X-Amz-Expires"] == ["900"]
    assert "content-type" in q["X-Amz-SignedHeaders"][0]
    get = storage.presign_get("org/output/job/a.sr.md", filename="a.sr.md", content_type="text/markdown")
    gq = parse_qs(urlsplit(get).query)
    assert gq["response-content-disposition"] == ["attachment; filename*=UTF-8''a.sr.md"]
    assert gq["X-Amz-Expires"] == ["300"]


def test_s3_requires_bucket():
    with pytest.raises(RuntimeError):
        storage.S3Storage(_s3_settings(s3_bucket=""))


def test_build_picks_backend(tmp_path):
    assert isinstance(storage.build(Settings(env="test", storage_dir=str(tmp_path))), storage.LocalStorage)
    with mock_aws():
        assert isinstance(storage.build(_s3_settings()), storage.S3Storage)
