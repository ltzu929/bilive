import os
from pathlib import Path

from src.server.worker_server import (
    configure_worker_environment,
    request_server_shutdown,
)


def test_configure_worker_environment_sets_project_paths(tmp_path, monkeypatch):
    for name in [
        "BILIVE_DIR",
        "BILIVE_CONFIG",
        "BILIVE_VIDEOS_DIR",
        "BILIVE_DB_PATH",
        "BILIVE_COOKIE_FILE",
        "BILIVE_AUTO_UPLOAD",
    ]:
        monkeypatch.delenv(name, raising=False)

    configure_worker_environment(tmp_path, auto_upload=False)

    assert Path(os.environ["BILIVE_DIR"]) == tmp_path.resolve()
    assert Path(os.environ["BILIVE_CONFIG"]) == (
        tmp_path / "bilive-server.toml"
    ).resolve()
    assert Path(os.environ["BILIVE_VIDEOS_DIR"]) == (
        tmp_path / "Videos"
    ).resolve()
    assert Path(os.environ["BILIVE_DB_PATH"]) == (
        tmp_path / "src" / "db" / "data.db"
    ).resolve()
    assert Path(os.environ["BILIVE_COOKIE_FILE"]) == (
        tmp_path / ".secrets" / "bilibili.cookie"
    ).resolve()
    assert os.environ["BILIVE_AUTO_UPLOAD"] == "0"
    assert os.environ["NO_PROXY"] == "127.0.0.1,localhost"


def test_shutdown_callback_sets_uvicorn_should_exit():
    server = type("Server", (), {"should_exit": False})()

    request_server_shutdown({"server": server})

    assert server.should_exit is True


def test_configure_worker_environment_loads_project_secret_env(tmp_path, monkeypatch):
    secret_dir = tmp_path / ".secrets"
    secret_dir.mkdir()
    (secret_dir / "env").write_text(
        "MIMO_API_KEY=project-secret\n# comment\nEMPTY=\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("MIMO_API_KEY", raising=False)

    configure_worker_environment(tmp_path, auto_upload=False)

    assert os.environ["MIMO_API_KEY"] == "project-secret"

def test_configure_worker_environment_uses_last_project_secret_value(tmp_path, monkeypatch):
    secret_dir = tmp_path / ".secrets"
    secret_dir.mkdir()
    (secret_dir / "env").write_text(
        "MIMO_API_KEY=old-secret\nMIMO_API_KEY=new-secret\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("MIMO_API_KEY", raising=False)

    configure_worker_environment(tmp_path, auto_upload=False)

    assert os.environ["MIMO_API_KEY"] == "new-secret"




def test_configure_worker_environment_reads_bom_prefixed_project_secret(tmp_path, monkeypatch):
    secret_dir = tmp_path / ".secrets"
    secret_dir.mkdir()
    (secret_dir / "env").write_bytes(
        b"\xef\xbb\xbfMIMO_API_KEY=project-secret\n"
    )
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    monkeypatch.delenv("\ufeffMIMO_API_KEY", raising=False)

    configure_worker_environment(tmp_path, auto_upload=False)

    assert os.environ["MIMO_API_KEY"] == "project-secret"
    assert "\ufeffMIMO_API_KEY" not in os.environ

def test_configure_worker_environment_keeps_existing_process_secret(tmp_path, monkeypatch):
    secret_dir = tmp_path / ".secrets"
    secret_dir.mkdir()
    (secret_dir / "env").write_text(
        "MIMO_API_KEY=project-secret\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MIMO_API_KEY", "process-secret")

    configure_worker_environment(tmp_path, auto_upload=False)

    assert os.environ["MIMO_API_KEY"] == "process-secret"
