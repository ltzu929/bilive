# Bilive PC Pipeline Launcher
# Starts LM Studio, scan_slice, and upload as detached background processes.
# Safe to close this PowerShell window after running — processes will survive.
#
# Usage: powershell -ExecutionPolicy Bypass -File start_pipeline.ps1
#   or just run in PowerShell: .\start_pipeline.ps1

param(
    [switch]$NoLMStudio,    # Skip LM Studio (if already running)
    [switch]$NoSlice,       # Skip scan_slice
    [switch]$NoUpload       # Skip upload
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

$env:PYTHONPATH = "$ProjectDir\src"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$pythonW = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonW) {
    Write-Warning "pythonw.exe not found, falling back to python.exe (may open console windows)"
    $pythonW = (Get-Command python.exe).Source
}

$logDir = "$ProjectDir\logs\runtime"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$dateSuffix = Get-Date -Format "yyyyMMdd-HHmmss"

Write-Host "=== Bilive Pipeline Launcher ==="
Write-Host "Project: $ProjectDir"
Write-Host "Python:  $pythonW"
Write-Host "Logs:    $logDir"
Write-Host ""

# ── 1. LM Studio ──
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
                Write-Warning "[LM Studio] API not responding after 60s. Pipeline may fail at LLM step."
            }
        }
    } else {
        Write-Warning "[LM Studio] Not found at $lmPath. LLM title generation will fail."
    }
}

# ── 2. scan_slice ──
if (-not $NoSlice) {
    $sliceLog = "$logDir\slice-$dateSuffix.log"
    Write-Host "[scan_slice] Starting (log: slice-$dateSuffix.log)..."
    $proc = Start-Process -FilePath $pythonW `
        -ArgumentList "-m", "src.burn.scan_slice" `
        -WindowStyle Hidden `
        -RedirectStandardOutput $sliceLog `
        -RedirectStandardError "$logDir\slice-$dateSuffix.err" `
        -PassThru
    Write-Host "[scan_slice] PID: $($proc.Id)"
}

# ── 3. upload ──
if (-not $NoUpload) {
    $uploadLog = "$logDir\upload-$dateSuffix.log"
    Write-Host "[upload] Starting (log: upload-$dateSuffix.log)..."
    $proc = Start-Process -FilePath $pythonW `
        -ArgumentList "-m", "src.upload.upload" `
        -WindowStyle Hidden `
        -RedirectStandardOutput $uploadLog `
        -RedirectStandardError "$logDir\upload-$dateSuffix.err" `
        -PassThru
    Write-Host "[upload] PID: $($proc.Id)"
}

Write-Host ""
Write-Host "=== Pipeline started. Safe to close this window. ==="
Write-Host "Monitor: Get-Content '$logDir\slice-$dateSuffix.log' -Wait -Tail 20"
