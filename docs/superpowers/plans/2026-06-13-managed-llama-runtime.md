# Managed llama.cpp Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the bilive Windows worker load the configured Qwen GGUF lazily once per run-once batch and unload it at batch exit without starting LM Studio.

**Architecture:** A focused runtime manager owns one `llama-server` child process and exposes a batch context plus a lazy OpenAI-compatible endpoint. The watcher owns the batch lifetime, the judge remains protocol-focused, and preflight validates files rather than a pre-existing service.

**Tech Stack:** Python 3.13, `subprocess`, `requests`, OpenAI Python SDK, PowerShell, official llama.cpp Windows CUDA 12 binaries, pytest.

---

### Task 1: Add managed runtime configuration

**Files:**
- Modify: `src/config/server_config.py`
- Modify: `src/config/__init__.py`
- Modify: `bilive-server.toml`
- Test: `tests/test_managed_llm_runtime.py`

- [ ] **Step 1: Write the failing configuration test**

```python
def test_managed_runtime_config_uses_environment_overrides(monkeypatch):
    monkeypatch.setenv("BILIVE_LLM_MODEL_PATH", r"E:\models\model.gguf")
    monkeypatch.setenv("BILIVE_LLAMA_SERVER_PATH", r"C:\runtime\llama-server.exe")
    config = importlib.reload(importlib.import_module("src.config.server_config"))
    assert config.MANAGED_LLM_MODEL_PATH == r"E:\models\model.gguf"
    assert config.MANAGED_LLAMA_SERVER_PATH == r"C:\runtime\llama-server.exe"
```

- [ ] **Step 2: Run the test and verify the missing constants fail**

Run: `python -m pytest tests/test_managed_llm_runtime.py -q`

Expected: `AttributeError` for `MANAGED_LLM_MODEL_PATH`.

- [ ] **Step 3: Add the managed settings**

Read `[slice.llm_judge]` into constants for model path, server path, host, port,
context size, GPU layers, parallel slots, startup timeout, and shutdown timeout.
Resolve the two path environment overrides before exporting them through
`src.config`.

- [ ] **Step 4: Run the focused test**

Run: `python -m pytest tests/test_managed_llm_runtime.py -q`

Expected: configuration test passes.

### Task 2: Implement the process owner

**Files:**
- Create: `src/autoslice/mllm_sdk/managed_runtime.py`
- Test: `tests/test_managed_llm_runtime.py`

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_batch_starts_lazily_reuses_process_and_stops_on_exit(runtime):
    with runtime.batch():
        assert runtime.status()["status"] == "idle"
        first = runtime.endpoint()
        second = runtime.endpoint()
        assert first == second
        assert runtime.process_factory.call_count == 1
    assert runtime.status()["status"] == "idle"
    runtime.process.terminate.assert_called_once()


def test_batch_stops_owned_process_after_exception(runtime):
    with pytest.raises(RuntimeError, match="pipeline failed"):
        with runtime.batch():
            runtime.endpoint()
            raise RuntimeError("pipeline failed")
    runtime.process.terminate.assert_called_once()
```

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/test_managed_llm_runtime.py -q`

Expected: import failure for `managed_runtime`.

- [ ] **Step 3: Implement the minimal runtime**

Add:

```python
class ManagedLlamaRuntime:
    def batch(self) -> ContextManager["ManagedLlamaRuntime"]: ...
    def endpoint(self) -> str: ...
    def start(self) -> str: ...
    def stop(self) -> None: ...
    def status(self) -> dict[str, object]: ...


def managed_llm_batch() -> ContextManager[ManagedLlamaRuntime]: ...
def managed_llm_endpoint() -> str: ...
def managed_llm_status() -> dict[str, object]: ...
```

Use an `RLock`, nested batch depth, lazy startup, an injected process factory
and HTTP probe for tests, and `try/finally` cleanup on the outermost batch.

- [ ] **Step 4: Add startup safety tests**

Cover missing executable, missing model, occupied port, early process exit,
readiness timeout, and forced kill after graceful shutdown timeout.

- [ ] **Step 5: Run focused lifecycle tests**

Run: `python -m pytest tests/test_managed_llm_runtime.py -q`

Expected: all runtime tests pass.

### Task 3: Integrate the runtime with judge and watcher

**Files:**
- Modify: `src/autoslice/mllm_sdk/judge.py`
- Modify: `src/server/watcher.py`
- Test: `tests/test_local_llm_judge.py`
- Test: `tests/test_watcher_once.py`

- [ ] **Step 1: Write failing integration tests**

```python
def test_managed_provider_uses_runtime_endpoint(monkeypatch):
    monkeypatch.setattr(judge, "_load_judge_provider_config", lambda: ("managed-llama-server", [], 120.0))
    monkeypatch.setattr(judge, "managed_llm_endpoint", lambda: "http://127.0.0.1:2236/v1")
    # Fake OpenAI and assert its base_url is the managed endpoint.


def test_process_pending_videos_owns_one_managed_batch(monkeypatch, tmp_path):
    events = []
    monkeypatch.setattr(watcher, "managed_llm_batch", recording_context(events))
    watcher.process_pending_videos(tmp_path)
    assert events == ["enter", "exit"]
```

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/test_local_llm_judge.py tests/test_watcher_once.py -q`

Expected: managed provider and batch assertions fail.

- [ ] **Step 3: Add minimal integration**

For the managed provider, fetch the runtime endpoint before constructing the
OpenAI client. Wrap the full body of `process_pending_videos()` in the batch
context so action jobs and all claimed recordings share one process.

- [ ] **Step 4: Run integration tests**

Run: `python -m pytest tests/test_local_llm_judge.py tests/test_watcher_once.py -q`

Expected: all focused tests pass.

### Task 4: Replace LM Studio preflight and expose runtime state

**Files:**
- Modify: `src/server/preflight.py`
- Modify: `src/server/worker_api.py`
- Test: `tests/test_worker_preflight.py`
- Test: `tests/test_worker_api.py`

- [ ] **Step 1: Write failing preflight and status tests**

```python
def test_managed_preflight_checks_runtime_and_model_without_http_listener(tmp_path):
    # Create fake executable and GGUF files.
    ready, message = preflight._check_llm(config)
    assert ready is True
    assert "managed" in message


def test_worker_status_includes_managed_llm_state():
    app = create_app(llm_status_reader=lambda: {"status": "idle"})
    assert response.json()["llm"] == {"status": "idle"}
```

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/test_worker_preflight.py tests/test_worker_api.py -q`

Expected: old LM Studio listener requirement and missing `llm` status fail.

- [ ] **Step 3: Implement file-based preflight and status injection**

Rename the internal check to `_check_llm`. For managed mode, resolve and validate
the configured files. Keep OpenAI-compatible HTTP probing for explicitly
configured external providers. Add an injectable runtime status reader to
`create_app`.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/test_worker_preflight.py tests/test_worker_api.py -q`

Expected: all focused tests pass.

### Task 5: Add the pinned runtime installer and remove LM Studio startup

**Files:**
- Create: `install_llama_runtime.ps1`
- Modify: `setup_windows_env.ps1`
- Modify: `start_pipeline.ps1`
- Modify: `install_windows_worker_task.ps1`
- Modify: `check_windows_health.ps1`
- Modify: `.gitignore`
- Test: `tests/test_pc_launcher.py`

- [ ] **Step 1: Update launcher tests first**

Assert:

```python
assert "LM Studio" not in pipeline_text
assert "BILIVE_LM_STUDIO_PATH" not in pipeline_text
assert "install_llama_runtime.ps1" in setup_text
assert "managed_llm" in health_text
assert ".runtime/" in gitignore_text
```

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/test_pc_launcher.py -q`

Expected: assertions fail against the LM Studio launcher.

- [ ] **Step 3: Add the installer**

Pin `b9616`, download the official Windows CUDA 12 llama.cpp archive and matching
CUDA DLL archive from the GitHub release, expand both into a temporary directory,
then atomically replace `.runtime/llama.cpp/b9616`. Verify
`llama-server.exe --version` before reporting success.

- [ ] **Step 4: Simplify launch and health scripts**

Remove `NoLMStudio`, `LMStudioPath`, process startup, port `1234`, and scheduled
task argument forwarding. `setup_windows_env.ps1` invokes the installer unless
`-SkipLlamaRuntime` is supplied. Health reports configured runtime/model
existence and current managed status from Worker API.

- [ ] **Step 5: Parse scripts and run tests**

Run:

```powershell
Get-ChildItem *.ps1 | ForEach-Object {
  [void][scriptblock]::Create((Get-Content -Raw -LiteralPath $_.FullName))
}
python -m pytest tests/test_pc_launcher.py -q
```

Expected: PowerShell parsing succeeds and launcher tests pass.

### Task 6: Verify and commit the runtime phase

**Files:**
- All files from Tasks 1-5

- [ ] **Step 1: Run the model-related suite**

Run:

```powershell
python -m pytest tests/test_managed_llm_runtime.py tests/test_local_llm_judge.py tests/test_watcher_once.py tests/test_worker_preflight.py tests/test_worker_api.py tests/test_pc_launcher.py -q
python -m compileall src tests
```

Expected: zero failures and compileall exits `0`.

- [ ] **Step 2: Install and smoke test the real runtime**

Run:

```powershell
.\install_llama_runtime.ps1
.\.venv-win\Scripts\python.exe -m src.autoslice.mllm_sdk.managed_runtime --smoke-test
```

Expected: Qwen returns a short JSON response, the child exits, and port `2236`
is no longer listening.

- [ ] **Step 3: Commit**

```powershell
git add bilive-server.toml .gitignore install_llama_runtime.ps1 setup_windows_env.ps1 start_pipeline.ps1 check_windows_health.ps1 src/config src/autoslice/mllm_sdk src/server tests/test_managed_llm_runtime.py tests/test_local_llm_judge.py tests/test_watcher_once.py tests/test_worker_preflight.py tests/test_worker_api.py
git commit -m "feat: manage llama model per worker batch"
```

Do not stage the pre-existing `install_windows_worker_task.ps1` and
`tests/test_pc_launcher.py` changes until their hunks have been separated and
reviewed.
