# bilive upload pipeline (standalone — use start_pipeline.ps1 for full launch)
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

$env:PYTHONPATH = "$ProjectDir;$ProjectDir\src"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:BILIVE_CONFIG = "$ProjectDir\bilive-server.toml"
$env:BILIVE_VIDEOS_DIR = "$ProjectDir\Videos"
$env:BILIVE_DB_PATH = "$ProjectDir\src\db\data.db"
$env:BILIVE_COOKIE_FILE = "$ProjectDir\.secrets\bilibili.cookie"

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
