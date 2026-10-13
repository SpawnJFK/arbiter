"""cli/arbiter-strings.mjs end to end: a real HTTP server on the test DB, an API key, push and pull.

Skipped when node is not installed. The CLI is zero-dependency Node; this proves it speaks
the same contract as the API tests (multipart push, query-string pull, Bearer API key)."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from str_helpers import client, project, register

from arbiter.api.app import create_app

CLI = Path(__file__).resolve().parents[4] / "cli" / "arbiter-strings.mjs"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server(db):
    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    t.join(timeout=5)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_cli_push_pull_release(server, tmp_path):
    c = client()
    h = register(c)
    key = c.post("/v1/api-keys", json={"name": "ci", "scopes": []}, headers=h).json()["key"]
    pid = project(c, h, target_langs=["de"])["id"]
    (tmp_path / "locales").mkdir()
    (tmp_path / "locales" / "en.json").write_text(
        json.dumps({"nav": {"home": "Home", "hello": "Hello {name}"}})
    )
    (tmp_path / "locales" / "de.json").write_text(json.dumps({"nav": {"home": "Start"}}))
    (tmp_path / "arbiter.strings.json").write_text(
        json.dumps(
            {
                "apiUrl": server,
                "projectId": pid,
                "files": [{"path": "locales/{lang}.json", "format": "json_nested"}],
            }
        )
    )
    env = {**os.environ, "ARBITER_TOKEN": key}

    def run(*args: str) -> str:
        r = subprocess.run(
            ["node", str(CLI), *args], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60
        )
        assert r.returncode == 0, r.stdout + r.stderr
        return r.stdout

    out = run("push", "--with-translations")
    assert "created 2" in out and "pushed locales/de.json (de" in out
    (tmp_path / "locales" / "de.json").unlink()
    out = run("pull", "--fallback")
    assert "pulled de" in out
    pulled = json.loads((tmp_path / "locales" / "de.json").read_text())
    assert pulled == {"nav": {"home": "Start", "hello": "Hello {name}"}}
    out = run("release", "--label", "1.0.0")
    assert "release 1.0.0 published" in out and "/ota/" in out
    status = run("status")
    assert "Notes app" in status and "2 keys" in status

    bad = subprocess.run(
        ["node", str(CLI), "pull"],
        cwd=tmp_path,
        env={**os.environ, "ARBITER_TOKEN": "nope"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert bad.returncode == 1 and "401" in bad.stderr
