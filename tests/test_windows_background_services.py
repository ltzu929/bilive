import os
import sys
import types
from pathlib import Path

import pytest

from src.server.dashboard_server import configure_dashboard_environment
from src.server.recorder_server import (
    configure_recorder_environment,
    install_secret_cookie,
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


def test_recorder_settings_dump_does_not_truncate_on_serialization_failure(
    tmp_path, monkeypatch
):
    class FakeSettings:
        @classmethod
        def load(cls, _path):
            return cls()

        def dict(self, *, exclude_none):
            assert exclude_none is True
            return {"header": {"cookie": "runtime-cookie"}, "version": "1.0"}

    blrec_module = types.ModuleType("blrec")
    setting_module = types.ModuleType("blrec.setting")
    setting_module.Settings = FakeSettings
    monkeypatch.setitem(sys.modules, "blrec", blrec_module)
    monkeypatch.setitem(sys.modules, "blrec.setting", setting_module)

    assert install_secret_cookie("runtime-cookie") is True

    settings_path = tmp_path / "settings.toml"
    settings_path.write_text("original", encoding="utf-8")

    settings = FakeSettings()
    settings._path = settings_path

    def fail_during_serialization(_payload):
        raise RuntimeError("serialization failed")

    import toml

    monkeypatch.setattr(toml, "dumps", fail_during_serialization)

    with pytest.raises(RuntimeError, match="serialization failed"):
        FakeSettings.dump(settings)

    assert settings_path.read_text(encoding="utf-8") == "original"


def test_recorder_app_uses_native_blrec_shell_and_api_gateway_without_injection():
    text = Path("src/server/recorder_app.py").read_text(encoding="utf-8")

    assert "from blrec.web import app as blrec_app" in text
    assert "StudioApiMiddleware(blrec_app)" in text
    assert "patch_installed_blrec_navigation" not in text


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
