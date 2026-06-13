from __future__ import annotations

import argparse
import os
import socket
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, ContextManager, Iterator

import httpx
import requests
from openai import OpenAI

from src.config import (
    BILIVE_DIR,
    LLM_JUDGE_PROVIDER,
    LOG_DIR,
    MANAGED_LLAMA_CONTEXT_SIZE,
    MANAGED_LLAMA_GPU_LAYERS,
    MANAGED_LLAMA_HOST,
    MANAGED_LLAMA_PARALLEL,
    MANAGED_LLAMA_PORT,
    MANAGED_LLAMA_SERVER_PATH,
    MANAGED_LLAMA_SHUTDOWN_TIMEOUT,
    MANAGED_LLAMA_STARTUP_TIMEOUT,
    MANAGED_LLM_MODEL_PATH,
    MULTI_MODAL_VISUAL_NAME,
)


ProcessFactory = Callable[..., subprocess.Popen]
HealthProbe = Callable[[str], bool]
PortChecker = Callable[[str, int], bool]


def create_local_openai_client(*, base_url: str, api_key: str) -> OpenAI:
    return OpenAI(
        base_url=base_url,
        api_key=api_key,
        http_client=httpx.Client(trust_env=False),
    )


def _message_output(message: object) -> str:
    content = str(getattr(message, "content", "") or "").strip()
    if content:
        return content
    return str(getattr(message, "reasoning_content", "") or "").strip()


def _resolve_project_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path(BILIVE_DIR) / path
    return path.resolve()


def _port_is_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


def _health_ready(url: str) -> bool:
    session = requests.Session()
    session.trust_env = False
    try:
        response = session.get(url, timeout=2)
    except requests.RequestException:
        return False
    return response.status_code == 200


def _popen_options() -> dict[str, int | bool]:
    if os.name != "nt":
        return {"start_new_session": True}
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return {"creationflags": flags}


class ManagedLlamaRuntime:
    def __init__(
        self,
        *,
        server_path: str | Path,
        model_path: str | Path,
        host: str,
        port: int,
        context_size: int,
        gpu_layers: str,
        parallel: int,
        startup_timeout: float,
        shutdown_timeout: float,
        log_path: str | Path,
        process_factory: ProcessFactory = subprocess.Popen,
        health_probe: HealthProbe = _health_ready,
        port_checker: PortChecker = _port_is_open,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.server_path = Path(server_path).expanduser().resolve()
        self.model_path = Path(model_path).expanduser().resolve()
        self.host = str(host)
        self.port = int(port)
        self.context_size = int(context_size)
        self.gpu_layers = str(gpu_layers)
        self.parallel = int(parallel)
        self.startup_timeout = float(startup_timeout)
        self.shutdown_timeout = float(shutdown_timeout)
        self.log_path = Path(log_path).expanduser().resolve()
        self.process_factory = process_factory
        self.health_probe = health_probe
        self.port_checker = port_checker
        self.monotonic = monotonic
        self.sleeper = sleeper
        self._process: subprocess.Popen | None = None
        self._batch_depth = 0
        self._started_at = 0.0
        self._lock = threading.RLock()

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def api_url(self) -> str:
        return f"{self.base_url}/v1"

    @contextmanager
    def batch(self) -> Iterator["ManagedLlamaRuntime"]:
        with self._lock:
            self._batch_depth += 1
        try:
            yield self
        finally:
            with self._lock:
                self._batch_depth = max(0, self._batch_depth - 1)
                should_stop = self._batch_depth == 0
            if should_stop:
                self.stop()

    @contextmanager
    def request(self) -> Iterator[str]:
        with self._lock:
            has_batch = self._batch_depth > 0
        if has_batch:
            yield self.endpoint()
            return
        with self.batch():
            yield self.endpoint()

    def endpoint(self) -> str:
        return self.start()

    def start(self) -> str:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return self.api_url
            self._process = None
            self._validate_files()
            if self.port_checker(self.host, self.port):
                raise RuntimeError(
                    f"llama-server port {self.host}:{self.port} is already in use"
                )

            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._process = self.process_factory(
                self._command(),
                cwd=str(self.server_path.parent),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                **_popen_options(),
            )
            self._started_at = time.time()
            deadline = self.monotonic() + self.startup_timeout

            while True:
                process = self._process
                if process is None:
                    raise RuntimeError("llama-server startup was interrupted")
                return_code = process.poll()
                if return_code is not None:
                    self._process = None
                    raise RuntimeError(
                        f"llama-server exited with code {return_code}"
                    )
                if self.health_probe(f"{self.base_url}/health"):
                    return self.api_url
                if self.monotonic() >= deadline:
                    self.stop()
                    raise RuntimeError(
                        f"llama-server did not become ready within "
                        f"{self.startup_timeout:g} seconds"
                    )
                self.sleeper(0.5)

    def stop(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=self.shutdown_timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=self.shutdown_timeout)

    def status(self) -> dict[str, object]:
        with self._lock:
            process = self._process
            if process is not None and process.poll() is None:
                return {
                    "status": "running",
                    "provider": LLM_JUDGE_PROVIDER,
                    "owned": True,
                    "pid": process.pid,
                    "started_at": self._started_at,
                    "model_path": str(self.model_path),
                    "endpoint": self.api_url,
                }
            if process is not None:
                self._process = None

            port_open = self.port_checker(self.host, self.port)
            if port_open:
                status = (
                    "running"
                    if self.health_probe(f"{self.base_url}/health")
                    else "occupied"
                )
            else:
                status = "idle"
            return {
                "status": status,
                "provider": LLM_JUDGE_PROVIDER,
                "owned": False,
                "model_path": str(self.model_path),
                "endpoint": self.api_url,
            }

    def _validate_files(self) -> None:
        if not self.server_path.is_file():
            raise RuntimeError(
                f"server executable not found: {self.server_path}"
            )
        if not self.model_path.is_file():
            raise RuntimeError(f"model file not found: {self.model_path}")

    def _command(self) -> list[str]:
        return [
            str(self.server_path),
            "--model",
            str(self.model_path),
            "--host",
            self.host,
            "--port",
            str(self.port),
            "--ctx-size",
            str(self.context_size),
            "--gpu-layers",
            self.gpu_layers,
            "--parallel",
            str(self.parallel),
            "--reasoning",
            "off",
            "--flash-attn",
            "auto",
            "--no-ui",
            "--log-file",
            str(self.log_path),
        ]


_managed_runtime: ManagedLlamaRuntime | None = None
_managed_runtime_lock = threading.Lock()


def get_managed_llm_runtime() -> ManagedLlamaRuntime:
    global _managed_runtime
    with _managed_runtime_lock:
        if _managed_runtime is None:
            _managed_runtime = ManagedLlamaRuntime(
                server_path=_resolve_project_path(MANAGED_LLAMA_SERVER_PATH),
                model_path=_resolve_project_path(MANAGED_LLM_MODEL_PATH),
                host=MANAGED_LLAMA_HOST,
                port=MANAGED_LLAMA_PORT,
                context_size=MANAGED_LLAMA_CONTEXT_SIZE,
                gpu_layers=MANAGED_LLAMA_GPU_LAYERS,
                parallel=MANAGED_LLAMA_PARALLEL,
                startup_timeout=MANAGED_LLAMA_STARTUP_TIMEOUT,
                shutdown_timeout=MANAGED_LLAMA_SHUTDOWN_TIMEOUT,
                log_path=Path(LOG_DIR) / "runtime" / "llama-server.log",
            )
        return _managed_runtime


def managed_llm_batch() -> ContextManager[ManagedLlamaRuntime]:
    return get_managed_llm_runtime().batch()


def managed_llm_request() -> ContextManager[str]:
    return get_managed_llm_runtime().request()


def managed_llm_endpoint() -> str:
    return get_managed_llm_runtime().endpoint()


def managed_llm_status() -> dict[str, object]:
    return get_managed_llm_runtime().status()


def _smoke_test() -> int:
    with managed_llm_request() as endpoint:
        client = create_local_openai_client(
            base_url=endpoint,
            api_key="bilive-managed",
        )
        completion = client.chat.completions.create(
            model=MULTI_MODAL_VISUAL_NAME,
            messages=[
                {
                    "role": "user",
                    "content": 'Return only this JSON object: {"status":"ok"}',
                }
            ],
            temperature=0,
            max_tokens=32,
            timeout=120,
            response_format={"type": "json_object"},
        )
        output = _message_output(completion.choices[0].message)
        if not output:
            raise RuntimeError("managed LLM smoke test returned no content")
        print(output)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args(argv)
    if args.smoke_test:
        return _smoke_test()
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
