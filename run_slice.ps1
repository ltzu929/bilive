# Run the pending slice queue once.
# This is the safe one-shot path used by the dashboard worker.

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

$env:PYTHONPATH = "$ProjectDir;$ProjectDir\src"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:BILIVE_CONFIG = "$ProjectDir\bilive-server.toml"
$env:BILIVE_VIDEOS_DIR = "$ProjectDir\Videos"

$logDir = "$ProjectDir\logs\runtime"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$dateSuffix = Get-Date -Format "yyyyMMdd-HHmmss"

$pythonW = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonW) { $pythonW = (Get-Command python.exe).Source }

$logPath = "$logDir\pc-worker-manual-$dateSuffix.log"
Start-Process -FilePath $pythonW `
    -ArgumentList "-m", "src.server.watcher", "--once", "--videos-dir", "$env:BILIVE_VIDEOS_DIR" `
    -WindowStyle Hidden `
    -RedirectStandardOutput $logPath `
    -RedirectStandardError $logPath

Write-Host "Pending slice worker started once. Log: $logPath"
