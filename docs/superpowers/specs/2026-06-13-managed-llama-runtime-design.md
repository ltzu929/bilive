# Managed llama.cpp Runtime Design

## Goal

Replace the always-on LM Studio dependency with a project-managed
`llama-server` process that loads
`E:\AImodel\lmstudio-community\Qwen3.5-9B-GGUF\Qwen3.5-9B-Q4_K_M.gguf`
only when a Windows worker batch first needs LLM judging and releases it when
that batch exits.

## Boundaries

- Pi continues to run recording and the dashboard only.
- The always-on Windows Worker API remains lightweight and does not load the
  model.
- One `src.server.watcher --once` invocation is one model lifecycle batch.
- Pure render work does not start the model.
- The first judge request starts `llama-server`; later judge requests in the
  same batch reuse it.
- Normal completion, failure, cancellation, and process exceptions all stop the
  owned server process in a `finally` path.
- A server already listening on the configured port is never killed or reused.
  The batch fails closed because ownership cannot be proven.

## Runtime

The project pins the official llama.cpp Windows CUDA 12 runtime to release
`b9616`. `install_llama_runtime.ps1` downloads the official Windows CUDA archive
and CUDA runtime DLL archive into `.runtime/llama.cpp/b9616/`. Runtime binaries
remain ignored by Git.

The managed process uses:

```text
llama-server.exe
  --model <model_path>
  --host 127.0.0.1
  --port 2236
  --ctx-size 4096
  --gpu-layers all
  --parallel 1
  --reasoning off
  --flash-attn auto
  --no-ui
  --log-file logs/runtime/llama-server.log
```

The manager waits for `GET /health` to report readiness. Early process exit,
timeout, missing files, or an occupied port produce a clear exception and leave
the candidate for manual review.

## Configuration

`bilive-server.toml` uses:

```toml
[slice.llm_judge]
provider = "managed-llama-server"
model_path = "E:\\AImodel\\lmstudio-community\\Qwen3.5-9B-GGUF\\Qwen3.5-9B-Q4_K_M.gguf"
server_path = ".runtime\\llama.cpp\\b9616\\llama-server.exe"
host = "127.0.0.1"
port = 2236
context_size = 4096
gpu_layers = "all"
parallel = 1
startup_timeout = 180
shutdown_timeout = 15
```

Machine-specific overrides remain possible through
`BILIVE_LLM_MODEL_PATH` and `BILIVE_LLAMA_SERVER_PATH`.

## Components

`src/autoslice/mllm_sdk/managed_runtime.py`

- Owns configuration validation, command construction, lazy process startup,
  health polling, status reporting, and shutdown.
- Exposes `managed_llm_batch()` and `managed_llm_endpoint()`.
- Tracks only a process it created. It does not attach to arbitrary listeners.

`src/server/watcher.py`

- Wraps action jobs and recording jobs in `managed_llm_batch()`.
- Keeps the runtime alive across all judge calls in one run-once batch.

`src/autoslice/mllm_sdk/judge.py`

- Uses the endpoint supplied by the managed runtime for
  `provider = "managed-llama-server"`.
- Keeps the existing OpenAI-compatible request and JSON parsing behavior.

`src/server/preflight.py`

- For the managed provider, validates the executable and model file instead of
  requiring an already-running HTTP server.

`src/server/worker_api.py`

- Includes managed runtime state in worker status without starting it.

## Failure Handling

- Missing model or runtime: preflight blocks worker startup and leaves pending
  markers untouched.
- Port conflict: runtime startup fails without terminating the unknown process.
- Model load timeout or early exit: judge returns `judge_failed`; candidates are
  retained.
- Worker exception: outer batch cleanup terminates the owned server.
- Graceful termination timeout: the manager kills only its owned process and
  waits for exit.
- Startup logs are persisted under `logs/runtime/` and contain no credentials.

## Verification

- Unit tests cover command construction, lazy start, reuse, startup failure,
  occupied-port refusal, and shutdown after exceptions.
- Watcher tests prove one batch context covers action and recording jobs.
- Preflight tests prove the server need not already be listening.
- Launcher tests prove LM Studio arguments and startup behavior are removed.
- A real smoke test loads the configured Qwen GGUF, calls
  `/v1/chat/completions`, exits the batch, and confirms port `2236` is closed.
