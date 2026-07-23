import hashlib
import json
import os
from pathlib import Path

import pytest

from src.server.dashboard_server import configure_dashboard_environment
from src.server.recorder_navigation import (
    INJECTION_START,
    patch_blrec_webapp_navigation,
)
from src.server.recorder_server import (
    configure_recorder_environment,
    persistent_settings_payload,
    read_secret_cookie,
)


def test_recorder_environment_loads_key_without_leaving_record_key(tmp_path, monkeypatch):
    secret_dir = tmp_path / ".secrets"
    secret_dir.mkdir()
    (secret_dir / "env").write_text("RECORD_KEY=abcdefgh\n", encoding="utf-8")
    (tmp_path / "settings.toml").write_text("version='1.0'\n", encoding="utf-8")
    for name in (
        "RECORD_KEY",
        "PYTHONPATH",
        "PYTHONUTF8",
        "PYTHONIOENCODING",
        "NO_PROXY",
        "no_proxy",
        "BLREC_API_KEY",
        "BLREC_CONFIG",
        "BLREC_OUT_DIR",
        "BLREC_LOG_DIR",
        "BLREC_PROGRESS",
        "BILIVE_RECORDER_COOKIE_FILE",
    ):
        monkeypatch.setenv(name, "__bilive_test_baseline__")
        monkeypatch.delenv(name)

    settings, videos, logs = configure_recorder_environment(tmp_path)

    assert settings == (tmp_path / "settings.toml").resolve()
    assert videos == (tmp_path / "Videos").resolve()
    assert logs == (tmp_path / "logs" / "record").resolve()
    assert os.environ["BLREC_API_KEY"] == "abcdefgh"
    assert Path(os.environ["BILIVE_RECORDER_COOKIE_FILE"]) == (
        tmp_path / ".secrets" / "bilibili.cookie"
    ).resolve()
    assert "RECORD_KEY" not in os.environ


def test_recorder_environment_requires_record_key(tmp_path, monkeypatch):
    monkeypatch.delenv("RECORD_KEY", raising=False)
    with pytest.raises(RuntimeError, match="RECORD_KEY"):
        configure_recorder_environment(tmp_path)


def test_cookie_reader_rejects_multiline_headers(tmp_path):
    cookie = tmp_path / "bilibili.cookie"
    cookie.write_text("SESSDATA=one\nbili_jct=two\n", encoding="utf-8")
    with pytest.raises(ValueError, match="one HTTP Cookie header line"):
        read_secret_cookie(cookie)


def test_persistent_settings_payload_removes_runtime_cookie():
    class FakeSettings:
        def dict(self, *, exclude_none):
            assert exclude_none is True
            return {"header": {"cookie": "private-cookie"}, "version": "1.0"}

    payload = persistent_settings_payload(FakeSettings())

    assert payload["header"]["cookie"] == ""
    assert payload["version"] == "1.0"


def test_recorder_navigation_patches_index_and_service_worker_once(tmp_path):
    webapp = tmp_path / "webapp"
    webapp.mkdir()
    index = webapp / "index.html"
    manifest = webapp / "ngsw.json"
    index.write_bytes(b'<html>\r\n<body><app-root></app-root>\r\n</body></html>\r\n')
    manifest.write_text(
        json.dumps({"timestamp": 1, "hashTable": {"/index.html": "old"}}),
        encoding="utf-8",
    )

    assert patch_blrec_webapp_navigation(webapp) is True

    patched_index = index.read_bytes()
    patched_text = patched_index.decode("utf-8")
    patched_manifest = json.loads(manifest.read_text(encoding="utf-8"))
    assert patched_text.count(INJECTION_START) == 1
    assert 'const navId = "bilive-studio-nav"' in patched_text
    assert 'link.textContent = "切片"' in patched_text
    assert ":${dashboardPort}/tasks" in patched_text
    assert b"\r\n" not in patched_index
    assert patched_manifest["hashTable"]["/index.html"] == hashlib.sha1(
        patched_index
    ).hexdigest()
    assert patched_manifest["timestamp"] > 1

    index_snapshot = index.read_bytes()
    manifest_snapshot = manifest.read_bytes()
    assert patch_blrec_webapp_navigation(webapp) is False
    assert index.read_bytes() == index_snapshot
    assert manifest.read_bytes() == manifest_snapshot


def test_dashboard_environment_keeps_upload_disabled(tmp_path, monkeypatch):
    for name in (
        "PYTHONPATH",
        "PYTHONUTF8",
        "PYTHONIOENCODING",
        "NO_PROXY",
        "no_proxy",
        "BILIVE_DIR",
        "BILIVE_CONFIG",
        "BILIVE_VIDEOS_DIR",
        "BILIVE_DB_PATH",
        "BILIVE_COOKIE_FILE",
        "BILIVE_AUTO_UPLOAD",
        "BILIVE_REMOTE_WORKER_ENABLED",
    ):
        monkeypatch.setenv(name, "__bilive_test_baseline__")
        monkeypatch.delenv(name)
    configure_dashboard_environment(tmp_path)

    assert os.environ["BILIVE_AUTO_UPLOAD"] == "0"
    assert os.environ["BILIVE_REMOTE_WORKER_ENABLED"] == "1"
    assert Path(os.environ["BILIVE_VIDEOS_DIR"]) == (tmp_path / "Videos").resolve()
