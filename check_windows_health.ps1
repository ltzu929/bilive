# Read-only health report for the Windows bilive worker.

param(
    [string]$TaskName = "BiliveWorkerApi",
    [string]$ProjectDir = (Split-Path -Parent $MyInvocation.MyCommand.Path)
)

$ErrorActionPreference = "Continue"
$ProjectDir = (Resolve-Path -LiteralPath $ProjectDir).Path
$python = Join-Path $ProjectDir ".venv-win\Scripts\python.exe"
$dbPath = Join-Path $ProjectDir "src\db\data.db"
$uploadLock = Join-Path $ProjectDir "logs\runtime\upload.lock"
$env:PYTHONPATH = $ProjectDir
$env:BILIVE_DIR = $ProjectDir
$env:BILIVE_CONFIG = Join-Path $ProjectDir "bilive-server.toml"

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
$listener = Get-NetTCPConnection `
    -LocalAddress "127.0.0.1" `
    -LocalPort 2235 `
    -State Listen `
    -ErrorAction SilentlyContinue

$api = $null
try {
    $api = Invoke-RestMethod `
        -Uri "http://127.0.0.1:2235/api/worker/status" `
        -TimeoutSec 3
} catch {
    $api = @{ status = "unavailable"; error = $_.Exception.Message }
}

$pythonChecks = @{
    python = $false
    faster_whisper = $false
    asr_model = ""
    database = "unavailable"
    managed_llm = @{ runtime = ""; model = ""; ready = $false }
}
if (Test-Path -LiteralPath $python) {
    $checkScript = @"
import importlib.util, json, sqlite3
from pathlib import Path
from src.config import BILIVE_DIR, MANAGED_LLAMA_SERVER_PATH, MANAGED_LLM_MODEL_PATH
def resolve(value):
    path = Path(value).expanduser()
    return (Path(BILIVE_DIR) / path).resolve() if not path.is_absolute() else path.resolve()
runtime = resolve(MANAGED_LLAMA_SERVER_PATH)
model = resolve(MANAGED_LLM_MODEL_PATH)
result = {
    "python": True,
    "faster_whisper": bool(importlib.util.find_spec("faster_whisper")),
    "asr_model": "",
    "database": "missing",
    "managed_llm": {
        "runtime": str(runtime),
        "runtime_exists": runtime.is_file(),
        "model": str(model),
        "model_exists": model.is_file(),
        "ready": runtime.is_file() and model.is_file(),
    },
}
try:
    from huggingface_hub import snapshot_download
    result["asr_model"] = snapshot_download(repo_id="Systran/faster-whisper-large-v3", local_files_only=True)
except Exception as exc:
    result["asr_model"] = f"unavailable: {exc}"
path = Path(r"$dbPath")
if path.is_file():
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    result["database"] = connection.execute("pragma integrity_check").fetchone()[0]
print(json.dumps(result, ensure_ascii=False))
"@
    try {
        $pythonChecks = ($checkScript | & $python - | ConvertFrom-Json)
    } catch {
        $pythonChecks = @{ python = $true; error = $_.Exception.Message }
    }
}

$report = [ordered]@{
    task = @{
        exists = [bool]$task
        state = if ($task) { [string]$task.State } else { "missing" }
        last_run_time = if ($taskInfo) { $taskInfo.LastRunTime } else { $null }
        last_result = if ($taskInfo) { $taskInfo.LastTaskResult } else { $null }
    }
    port_2235_listening = [bool]$listener
    worker_api = $api
    managed_llm = @{
        files = $pythonChecks.managed_llm
        process = if ($api -and $api.llm) { $api.llm } else { $null }
    }
    dependencies = $pythonChecks
    upload_lock = @{
        path = $uploadLock
        exists = Test-Path -LiteralPath $uploadLock
    }
}

$report | ConvertTo-Json -Depth 10
