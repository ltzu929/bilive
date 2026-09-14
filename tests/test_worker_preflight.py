import importlib
import sys
import types
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
        llm_checker=lambda _config, _root: (True, "ready"),
        asr_checker=lambda _config: (True, "cached"),
    )

    assert result["ready"] is True
    assert result["unavailable"] == []
    assert result["checks"]["videos"]["status"] == "ready"
    assert result["checks"]["database"]["status"] == "ready"


def test_worker_preflight_blocks_when_llm_is_unavailable(tmp_path):
    preflight = _module()
    from src.db.conn import migrate_upload_queue

    videos = tmp_path / "Videos"
    videos.mkdir()
    migrate_upload_queue(tmp_path / "queue.db")

    result = preflight.run_worker_preflight(
        project_root=tmp_path,
        videos_root=videos,
        db_path=tmp_path / "queue.db",
        llm_checker=lambda _config, _root: (False, "runtime missing"),
        asr_checker=lambda _config: (True, "cached"),
    )

    assert result["ready"] is False
    assert result["unavailable"] == ["llm"]
    assert result["checks"]["llm"] == {
        "status": "unavailable",
        "message": "runtime missing",
    }


def test_worker_preflight_fails_closed_for_output_database_and_asr(tmp_path):
    preflight = _module()
    database_directory = tmp_path / "queue.db"
    database_directory.mkdir()

    result = preflight.run_worker_preflight(
        project_root=tmp_path,
        videos_root=tmp_path / "missing-videos",
        db_path=database_directory,
        llm_checker=lambda _config, _root: (True, "ready"),
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


def test_cuda_asr_check_fails_closed_when_runtime_is_unavailable(tmp_path, monkeypatch):
    preflight = _module()
    model = tmp_path / "large-v3"
    model.mkdir()
    monkeypatch.setattr(preflight.importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setattr(
        preflight,
        "_check_cuda_asr_runtime",
        lambda *_args: (False, "faster-whisper CUDA initialization failed: cublas64_12.dll"),
    )

    ready, message = preflight._check_asr(
        {
            "slice": {
                "multi_modal": {
                    "whisper_model": str(model),
                    "whisper_device": "cuda",
                    "whisper_compute_type": "float16",
                }
            }
        }
    )

    assert ready is False
    assert "cublas64_12.dll" in message


def test_cuda_asr_check_reports_ready_after_runtime_validation(tmp_path, monkeypatch):
    preflight = _module()
    model = tmp_path / "large-v3"
    model.mkdir()
    monkeypatch.setattr(preflight.importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setattr(
        preflight,
        "_check_cuda_asr_runtime",
        lambda *_args: (True, "CUDA ASR ready: device_count=1, compute_type=float16"),
    )

    ready, message = preflight._check_asr(
        {
            "slice": {
                "multi_modal": {
                    "whisper_model": str(model),
                    "whisper_device": "cuda",
                    "whisper_compute_type": "float16",
                }
            }
        }
    )

    assert ready is True
    assert message.endswith("compute_type=float16")


def test_cuda_asr_check_runs_a_real_probe_before_reporting_ready(tmp_path, monkeypatch):
    preflight = _module()
    model = tmp_path / "large-v3"
    model.mkdir()
    calls = []

    class FakeWhisperModel:
        def __init__(self, *args, **kwargs):
            calls.append((args, kwargs))

        def transcribe(self, audio, **kwargs):
            assert len(audio) == 16000
            assert kwargs["without_timestamps"] is True
            return iter(()), object()

    monkeypatch.setitem(
        sys.modules,
        "ctranslate2",
        types.SimpleNamespace(
            get_cuda_device_count=lambda: 1,
            get_supported_compute_types=lambda _device: {"float16"},
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        types.SimpleNamespace(WhisperModel=FakeWhisperModel),
    )
    preflight._check_cuda_asr_runtime.cache_clear()

    ready, message = preflight._check_cuda_asr_runtime(
        str(model),
        "float16",
        8,
    )

    assert ready is True
    assert "CUDA ASR ready" in message
    assert calls and calls[0][1]["device"] == "cuda"


def test_cuda_asr_check_keeps_worker_unavailable_when_probe_fails(tmp_path, monkeypatch):
    preflight = _module()
    model = tmp_path / "large-v3"
    model.mkdir()

    class FakeWhisperModel:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, *_args, **_kwargs):
            raise RuntimeError("cublas64_12.dll is not found or cannot be loaded")

    monkeypatch.setitem(
        sys.modules,
        "ctranslate2",
        types.SimpleNamespace(
            get_cuda_device_count=lambda: 1,
            get_supported_compute_types=lambda _device: {"float16"},
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        types.SimpleNamespace(WhisperModel=FakeWhisperModel),
    )
    preflight._check_cuda_asr_runtime.cache_clear()

    ready, message = preflight._check_cuda_asr_runtime(
        str(model),
        "float16",
        8,
    )

    assert ready is False
    assert "cublas64_12.dll" in message


def test_mimo_check_requires_environment_api_key(monkeypatch, tmp_path):
    preflight = _module()
    monkeypatch.delenv("MIMO_API_KEY", raising=False)

    ready, message = preflight._check_llm({}, tmp_path)

    assert ready is False
    assert message == "MIMO_API_KEY is not set"


def test_mimo_check_does_not_validate_legacy_llama_files(monkeypatch, tmp_path):
    preflight = _module()
    monkeypatch.setenv("MIMO_API_KEY", "secret-key")

    ready, message = preflight._check_llm(
        {
            "slice": {
                "llm_judge": {
                    "provider": "managed-llama-server",
                    "server_path": str(tmp_path / "missing-llama-server.exe"),
                    "model_path": str(tmp_path / "missing-model.gguf"),
                },
                "mimo": {
                    "model": "mimo-v2.5",
                    "base_url": "https://api.xiaomimimo.com/v1",
                },
            }
        },
        tmp_path,
    )

    assert ready is True
    assert message == "MiMo API key configured for mimo-v2.5"
    assert "secret" not in message.lower()


def test_worker_preflight_does_not_create_missing_database(tmp_path):
    preflight = _module()
    videos = tmp_path / "Videos"
    videos.mkdir()
    database = tmp_path / "queue.db"

    result = preflight.run_worker_preflight(
        project_root=tmp_path,
        videos_root=videos,
        db_path=database,
        llm_checker=lambda _config, _root: (True, "ready"),
        asr_checker=lambda _config: (True, "cached"),
    )

    assert result["checks"]["database"]["status"] == "unavailable"
    assert not database.exists()
