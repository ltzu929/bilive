# bilive upload pipeline (standalone — use start_pipeline.ps1 for full launch)
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = "$ProjectDir\src"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$logDir = "$ProjectDir\logs\runtime"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$dateSuffix = Get-Date -Format "yyyyMMdd-HHmmss"

$pythonW = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonW) { $pythonW = (Get-Command python.exe).Source }

Start-Process -FilePath $pythonW `
    -ArgumentList "-m", "src.upload.upload" `
    -WindowStyle Hidden `
    -RedirectStandardOutput "$logDir\upload-$dateSuffix.log" `
    -RedirectStandardError "$logDir\upload-$dateSuffix.err"

Write-Host "upload started. Log: $logDir\upload-$dateSuffix.log"
