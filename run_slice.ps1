# bilive slice pipeline (standalone — use start_pipeline.ps1 for full launch)
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
    -ArgumentList "-m", "src.burn.scan_slice" `
    -WindowStyle Hidden `
    -RedirectStandardOutput "$logDir\slice-$dateSuffix.log" `
    -RedirectStandardError "$logDir\slice-$dateSuffix.err"

Write-Host "scan_slice started. Log: $logDir\slice-$dateSuffix.log"
