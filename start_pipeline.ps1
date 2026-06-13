# Bilive Windows supervisor. This is the only production PC entrypoint.

param(
    [switch]$NoUpload
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectDir

$python = Join-Path $ProjectDir ".venv-win\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Windows environment missing: $python. Run setup_windows_env.ps1 first."
}

$env:PYTHONPATH = $ProjectDir
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:NO_PROXY = "127.0.0.1,localhost"
$env:no_proxy = $env:NO_PROXY
$env:BILIVE_DIR = $ProjectDir
$env:BILIVE_CONFIG = Join-Path $ProjectDir "bilive-server.toml"
$env:BILIVE_VIDEOS_DIR = Join-Path $ProjectDir "Videos"
$env:BILIVE_DB_PATH = Join-Path $ProjectDir "src\db\data.db"
$env:BILIVE_COOKIE_FILE = Join-Path $ProjectDir ".secrets\bilibili.cookie"
if ($NoUpload) {
    $env:BILIVE_AUTO_UPLOAD = "0"
} else {
    $env:BILIVE_AUTO_UPLOAD = "1"
}

$logDir = Join-Path $ProjectDir "logs\runtime"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

Write-Host "Bilive Worker API: http://127.0.0.1:2235"
Write-Host "Upload consumer is managed by the Worker API."
& $python "-c" "from src.db.conn import migrate_upload_queue; migrate_upload_queue()"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to initialize the upload database"
}
$uvicornNetworkArgs = @("--host", "127.0.0.1", "--port", "2235")
& $python "-m" "uvicorn" "src.server.worker_api:api" @uvicornNetworkArgs
exit $LASTEXITCODE
