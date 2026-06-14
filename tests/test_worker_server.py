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
