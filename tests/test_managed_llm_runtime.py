import importlib
import subprocess
import threading
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock

import pytest


class FakeProcess:
    def __init__(self, *, poll_result=None, wait_timeout=False):
        self.pid = 4321
        self._poll_result = poll_result
        self._wait_timeout = wait_timeout
        self.terminated = False
        self.killed = False

    def poll(self):
        return self._poll_result

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True
        self._wait_timeout = False

    def wait(self, timeout=None):
        if self._wait_timeout:
            raise subprocess.TimeoutExpired("llama-server", timeout)
        self._poll_result = 0
        return 0


def _runtime(tmp_path, **overrides):
    from src.autoslice.mllm_sdk.managed_runtime import ManagedLlamaRuntime

    server = tmp_path / "llama-server.exe"
    model = tmp_path / "model.gguf"
    server.write_bytes(b"exe")
    model.write_bytes(b"gguf")
    defaults = {
        "server_path": server,
        "model_path": model,
        "host": "127.0.0.1",
        "port": 2236,
        "context_size": 4096,
        "gpu_layers": "all",
        "parallel": 1,
        "startup_timeout": 10,
        "shutdown_timeout": 2,
        "log_path": tmp_path / "runtime.log",
        "process_factory": Mock(return_value=FakeProcess()),
        "health_probe": Mock(return_value=True),
        "port_checker": Mock(return_value=False),
        "monotonic": Mock(side_effect=[0, 0]),
        "sleeper": Mock(),
    }
    defaults.update(overrides)
    return ManagedLlamaRuntime(**defaults)


def test_managed_runtime_config_uses_environment_overrides(monkeypatch):
    monkeypatch.setenv("BILIVE_LLM_MODEL_PATH", r"E:\models\model.gguf")
    monkeypatch.setenv(
        "BILIVE_LLAMA_SERVER_PATH",
        r"C:\runtime\llama-server.exe",
    )
    config = importlib.reload(importlib.import_module("src.config.server_config"))

    assert config.MANAGED_LLM_MODEL_PATH == r"E:\models\model.gguf"
    assert config.MANAGED_LLAMA_SERVER_PATH == r"C:\runtime\llama-server.exe"

    monkeypatch.delenv("BILIVE_LLM_MODEL_PATH")
    monkeypatch.delenv("BILIVE_LLAMA_SERVER_PATH")
    importlib.reload(config)
    importlib.reload(importlib.import_module("src.config"))


def test_batch_starts_lazily_reuses_process_and_stops_on_exit(tmp_path):
    process = FakeProcess()
    process_factory = Mock(return_value=process)
    runtime = _runtime(tmp_path, process_factory=process_factory)

    with runtime.batch():
        assert runtime.status()["status"] == "idle"
        first = runtime.endpoint()
        second = runtime.endpoint()
        assert first == second == "http://127.0.0.1:2236/v1"
        assert process_factory.call_count == 1
        assert runtime.status()["status"] == "running"

    assert runtime.status()["status"] == "idle"
    assert process.terminated is True


def test_concurrent_start_waits_until_health_check_passes(tmp_path):
    entered_health_check = threading.Event()
    release_health_check = threading.Event()
    process_factory = Mock(return_value=FakeProcess())
    results = []

    def health_probe(_url):
        entered_health_check.set()
        release_health_check.wait(timeout=2)
        return True

    runtime = _runtime(
        tmp_path,
        process_factory=process_factory,
        health_probe=health_probe,
    )

    first = threading.Thread(target=lambda: results.append(runtime.start()))
    second = threading.Thread(target=lambda: results.append(runtime.start()))
    first.start()
    assert entered_health_check.wait(timeout=1)
    second.start()

    second.join(timeout=0.05)
    assert second.is_alive()

    release_health_check.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert results == [
        "http://127.0.0.1:2236/v1",
        "http://127.0.0.1:2236/v1",
    ]
    assert process_factory.call_count == 1
    runtime.stop()


def test_batch_stops_owned_process_after_exception(tmp_path):
    process = FakeProcess()
    runtime = _runtime(tmp_path, process_factory=Mock(return_value=process))

    with pytest.raises(RuntimeError, match="pipeline failed"):
        with runtime.batch():
            runtime.endpoint()
            raise RuntimeError("pipeline failed")

    assert process.terminated is True
    assert runtime.status()["status"] == "idle"


def test_request_outside_batch_uses_one_shot_lifecycle(tmp_path):
    process = FakeProcess()
    runtime = _runtime(tmp_path, process_factory=Mock(return_value=process))

    with runtime.request() as endpoint:
        assert endpoint == "http://127.0.0.1:2236/v1"
        assert runtime.status()["status"] == "running"

    assert process.terminated is True
    assert runtime.status()["status"] == "idle"


@pytest.mark.parametrize("missing", ["server", "model"])
def test_start_rejects_missing_required_file(tmp_path, missing):
    runtime = _runtime(tmp_path)
    path = runtime.server_path if missing == "server" else runtime.model_path
    Path(path).unlink()

    with pytest.raises(RuntimeError, match=f"{missing}.*not found"):
        with runtime.batch():
            runtime.endpoint()


def test_start_refuses_an_occupied_port_without_spawning(tmp_path):
    process_factory = Mock()
    runtime = _runtime(
        tmp_path,
        process_factory=process_factory,
        port_checker=Mock(return_value=True),
    )

    with pytest.raises(RuntimeError, match="already in use"):
        with runtime.batch():
            runtime.endpoint()

    process_factory.assert_not_called()


def test_start_reports_early_process_exit(tmp_path):
    process = FakeProcess(poll_result=7)
    runtime = _runtime(
        tmp_path,
        process_factory=Mock(return_value=process),
        health_probe=Mock(return_value=False),
    )

    with pytest.raises(RuntimeError, match="exited with code 7"):
        with runtime.batch():
            runtime.endpoint()


def test_start_timeout_stops_the_owned_process(tmp_path):
    process = FakeProcess()
    runtime = _runtime(
        tmp_path,
        startup_timeout=1,
        process_factory=Mock(return_value=process),
        health_probe=Mock(return_value=False),
        monotonic=Mock(side_effect=[0, 2]),
    )

    with pytest.raises(RuntimeError, match="did not become ready"):
        with runtime.batch():
            runtime.endpoint()

    assert process.terminated is True


def test_stop_kills_process_that_ignores_terminate(tmp_path):
    process = FakeProcess(wait_timeout=True)
    runtime = _runtime(tmp_path, process_factory=Mock(return_value=process))

    with runtime.batch():
        runtime.endpoint()

    assert process.terminated is True
    assert process.killed is True


def test_status_detects_managed_server_started_by_worker_process(tmp_path):
    runtime = _runtime(
        tmp_path,
        port_checker=Mock(return_value=True),
        health_probe=Mock(return_value=True),
    )

    assert runtime.status() == {
        "status": "running",
        "provider": "managed-llama-server",
        "owned": False,
        "model_path": str(runtime.model_path),
        "endpoint": "http://127.0.0.1:2236/v1",
    }


def test_status_reports_unknown_port_occupant(tmp_path):
    runtime = _runtime(
        tmp_path,
        port_checker=Mock(return_value=True),
        health_probe=Mock(return_value=False),
    )

    assert runtime.status() == {
        "status": "occupied",
        "provider": "managed-llama-server",
        "owned": False,
        "model_path": str(runtime.model_path),
        "endpoint": "http://127.0.0.1:2236/v1",
    }


def test_command_contains_model_and_gpu_settings(tmp_path):
    process_factory = Mock(return_value=FakeProcess())
    runtime = _runtime(tmp_path, process_factory=process_factory)

    with runtime.batch():
        runtime.endpoint()

    command = process_factory.call_args.args[0]
    assert command[:2] == [str(runtime.server_path), "--model"]
    assert str(runtime.model_path) in command
    assert command[command.index("--port") + 1] == "2236"
    assert command[command.index("--ctx-size") + 1] == "4096"
    assert command[command.index("--gpu-layers") + 1] == "all"
    assert command[command.index("--reasoning") + 1] == "off"
    assert "--no-ui" in command


def test_local_openai_client_disables_environment_proxy(monkeypatch):
    from src.autoslice.mllm_sdk import managed_runtime

    calls = {}
    transport = object()

    class Httpx:
        @staticmethod
        def Client(**kwargs):
            calls["httpx"] = kwargs
            return transport

    class OpenAI:
        def __init__(self, **kwargs):
            calls["openai"] = kwargs

    monkeypatch.setattr(managed_runtime, "httpx", Httpx)
    monkeypatch.setattr(managed_runtime, "OpenAI", OpenAI)

    managed_runtime.create_local_openai_client(
        base_url="http://127.0.0.1:2236/v1",
        api_key="test",
    )

    assert calls["httpx"] == {"trust_env": False}
    assert calls["openai"]["http_client"] is transport


def test_message_output_accepts_qwen_reasoning_content():
    from src.autoslice.mllm_sdk.managed_runtime import _message_output

    message = type(
        "Message",
        (),
        {"content": "", "reasoning_content": '{"status":"ok"}'},
    )()

    assert _message_output(message) == '{"status":"ok"}'


def test_smoke_test_requests_json_response(monkeypatch, capsys):
    from src.autoslice.mllm_sdk import managed_runtime

    calls = {}
    message = type("Message", (), {"content": '{"status":"ok"}'})()
    completion = type(
        "Completion",
        (),
        {"choices": [type("Choice", (), {"message": message})()]},
    )()

    class Completions:
        @staticmethod
        def create(**kwargs):
            calls.update(kwargs)
            return completion

    client = type(
        "Client",
        (),
        {
            "chat": type(
                "Chat",
                (),
                {"completions": Completions()},
            )()
        },
    )()
    monkeypatch.setattr(
        managed_runtime,
        "managed_llm_request",
        lambda: nullcontext("http://127.0.0.1:2236/v1"),
    )
    monkeypatch.setattr(
        managed_runtime,
        "create_local_openai_client",
        lambda **_kwargs: client,
    )

    assert managed_runtime._smoke_test() == 0
    assert calls["response_format"] == {"type": "json_object"}
    assert capsys.readouterr().out.strip() == '{"status":"ok"}'
