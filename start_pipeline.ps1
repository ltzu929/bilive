# Bilive PC launcher.
# Starts local helper services for the dashboard workflow:
# - optional LM Studio
# - local PC worker API on 127.0.0.1:2235
# - upload queue consumer managed by the worker API
#
# It does not start the legacy full-directory scan_slice loop by default.
# Queue slice jobs from /tasks, then the browser will trigger the one-shot worker.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File start_pipeline.ps1
#   .\start_pipeline.ps1 -NoUpload
#   .\start_pipeline.ps1 -RunLegacyScanSlice   # compatibility only, one scan pass

param(
    [switch]$NoLMStudio,
    [switch]$NoWorkerApi,
    [switch]$NoUpload,
    [switch]$RunLegacyScanSlice,
    [switch]$NoSlice
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

$env:PYTHONPATH = "$ProjectDir;$ProjectDir\src"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:BILIVE_CONFIG = "$ProjectDir\bilive-server.toml"
$env:BILIVE_VIDEOS_DIR = "$ProjectDir\Videos"
$env:BILIVE_DB_PATH = "$ProjectDir\src\db\data.db"
$env:BILIVE_COOKIE_FILE = "$ProjectDir\.secrets\bilibili.cookie"
if ($NoUpload) {
    $env:BILIVE_AUTO_UPLOAD = "0"
} elseif (-not $env:BILIVE_AUTO_UPLOAD) {
    $env:BILIVE_AUTO_UPLOAD = "1"
}

$pythonW = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonW) {
    Write-Warning "pythonw.exe not found, falling back to python.exe (may open console windows)"
    $pythonW = (Get-Command python.exe).Source
}

$logDir = "$ProjectDir\logs\runtime"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$dateSuffix = Get-Date -Format "yyyyMMdd-HHmmss"

Write-Host "=== Bilive PC Launcher ==="
Write-Host "Project: $ProjectDir"
Write-Host "Python:  $pythonW"
Write-Host "Logs:    $logDir"
Write-Host ""

if ($NoSlice) {
    Write-Warning "-NoSlice is deprecated and now a no-op. Legacy scan_slice is disabled unless -RunLegacyScanSlice is set."
}

# 1. LM Studio
$lmPath = "D:\LMStudio\LM Studio\LM Studio.exe"
if (-not $NoLMStudio) {
    if (Test-Path $lmPath) {
        if (Get-Process "LM Studio" -ErrorAction SilentlyContinue) {
            Write-Host "[LM Studio] Already running."
        } else {
            Write-Host "[LM Studio] Starting..."
            Start-Process -FilePath $lmPath -WindowStyle Minimized
            Write-Host "[LM Studio] Waiting for API (port 6542)..."
            $ready = $false
            for ($i = 0; $i -lt 20; $i++) {
                Start-Sleep -Seconds 3
                try {
                    $null = Invoke-WebRequest "http://100.118.141.26:6542/v1/models" -UseBasicParsing -TimeoutSec 2
                    $ready = $true
                    break
                } catch { }
            }
            if ($ready) {
                Write-Host "[LM Studio] API ready."
            } else {
                Write-Warning "[LM Studio] API not responding after 60s. LLM title generation may fall back."
            }
        }
    } else {
        Write-Warning "[LM Studio] Not found at $lmPath. LLM title generation may fall back."
    }
}

# 2. PC worker API
if (-not $NoWorkerApi) {
    $workerApiLog = "$logDir\worker-api-$dateSuffix.log"
    $workerApiRunning = $false
    try {
        $null = Invoke-WebRequest "http://127.0.0.1:2235/api/worker/status" -UseBasicParsing -TimeoutSec 2
        $workerApiRunning = $true
    } catch { }

    if ($workerApiRunning) {
        Write-Host "[worker_api] Already running on port 2235."
    } else {
        Write-Host "[worker_api] Starting (log: worker-api-$dateSuffix.log)..."
        $proc = Start-Process -FilePath $pythonW `
            -ArgumentList "-m", "uvicorn", "src.server.worker_api:api", "--host", "127.0.0.1", "--port", "2235" `
            -WindowStyle Hidden `
            -RedirectStandardOutput $workerApiLog `
            -RedirectStandardError "$logDir\worker-api-$dateSuffix.err" `
            -PassThru
        Write-Host "[worker_api] PID: $($proc.Id)"
    }
}

# 3. Legacy compatibility path
if ($RunLegacyScanSlice) {
    $sliceLog = "$logDir\slice-legacy-$dateSuffix.log"
    Write-Warning "[scan_slice] Running legacy full-directory scan once. Prefer /tasks + PC worker for daily use."
    $proc = Start-Process -FilePath $pythonW `
        -ArgumentList "-m", "src.burn.scan_slice", "--once" `
        -WindowStyle Hidden `
        -RedirectStandardOutput $sliceLog `
        -RedirectStandardError "$logDir\slice-legacy-$dateSuffix.err" `
        -PassThru
    Write-Host "[scan_slice] PID: $($proc.Id)"
}

Write-Host ""
Write-Host "=== PC helpers started. Safe to close this window. ==="
Write-Host "Slice workflow: open /tasks and click Start Slice."
Write-Host "Worker API: http://127.0.0.1:2235/api/worker/status"
Write-Host "Upload status: http://127.0.0.1:2235/api/upload/status"
