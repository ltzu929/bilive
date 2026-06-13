import importlib
from pathlib import Path


def _module():
    assert Path("src/server/preflight.py").exists(), "worker preflight module is missing"
    return importlib.import_module("src.server.preflight")


def test_worker_preflight_reports_ready_dependencies(tmp_path):
    preflight = _module()
    from src.db.conn import migrate_upload_queue

    videos = tmp_path / "Videos"
    videos.mkdir()
    migrate_upload_queue(tmp_path / "queue.db")

    result = preflight.run_worker_preflight(
        project_root=tmp_path,
        videos_root=videos,
        db_path=tmp_path / "queue.db",
        lm_studio_checker=lambda _config: (True, "ready"),
        asr_checker=lambda _config: (True, "cached"),
    )

    assert result["ready"] is True
    assert result["unavailable"] == []
    assert result["checks"]["videos"]["status"] == "ready"
    assert result["checks"]["database"]["status"] == "ready"


def test_worker_preflight_blocks_when_lm_studio_is_unavailable(tmp_path):
    preflight = _module()
    from src.db.conn import migrate_upload_queue

    videos = tmp_path / "Videos"
    videos.mkdir()
    migrate_upload_queue(tmp_path / "queue.db")

    result = preflight.run_worker_preflight(
        project_root=tmp_path,
        videos_root=videos,
        db_path=tmp_path / "queue.db",
        lm_studio_checker=lambda _config: (False, "connection refused"),
        asr_checker=lambda _config: (True, "cached"),
    )

    assert result["ready"] is False
    assert result["unavailable"] == ["lm_studio"]
    assert result["checks"]["lm_studio"] == {
        "status": "unavailable",
        "message": "connection refused",
    }


def test_worker_preflight_fails_closed_for_output_database_and_asr(tmp_path):
    preflight = _module()
    database_directory = tmp_path / "queue.db"
    database_directory.mkdir()

    result = preflight.run_worker_preflight(
        project_root=tmp_path,
        videos_root=tmp_path / "missing-videos",
        db_path=database_directory,
        lm_studio_checker=lambda _config: (True, "ready"),
        asr_checker=lambda _config: (False, "model missing"),
    )

    assert result["ready"] is False
    assert set(result["unavailable"]) == {"videos", "database", "asr"}
    assert result["checks"]["videos"]["status"] == "unavailable"
    assert result["checks"]["database"]["status"] == "unavailable"
    assert result["checks"]["asr"] == {
        "status": "unavailable",
        "message": "model missing",
    }


def test_asr_check_cannot_be_disabled_while_pipeline_requires_it(monkeypatch):
    preflight = _module()
    monkeypatch.setattr(preflight.importlib.util, "find_spec", lambda _name: None)

    ready, message = preflight._check_asr(
        {"slice": {"multi_modal": {"enable_audio": False}}}
    )

    assert ready is False
    assert message == "faster-whisper is not installed"


def test_lm_studio_check_does_not_use_environment_proxy(monkeypatch):
    preflight = _module()
    calls = {}

    class Response:
        def raise_for_status(self):
            return None

    class Session:
        trust_env = True

        def get(self, url, timeout):
            calls["trust_env"] = self.trust_env
            calls["url"] = url
            return Response()

    monkeypatch.setattr(preflight.requests, "Session", Session)

    ready, _message = preflight._check_lm_studio({})

    assert ready is True
    assert calls["trust_env"] is False
    assert calls["url"] == "http://127.0.0.1:1234/v1/models"


def test_worker_preflight_does_not_create_missing_database(tmp_path):
    preflight = _module()
    videos = tmp_path / "Videos"
    videos.mkdir()
    database = tmp_path / "queue.db"

    result = preflight.run_worker_preflight(
        project_root=tmp_path,
        videos_root=videos,
        db_path=database,
        lm_studio_checker=lambda _config: (True, "ready"),
        asr_checker=lambda _config: (True, "cached"),
    )

    assert result["checks"]["database"]["status"] == "unavailable"
    assert not database.exists()
