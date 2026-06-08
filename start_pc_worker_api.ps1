$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

$env:PYTHONPATH = "$ProjectDir;$ProjectDir\src"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:BILIVE_CONFIG = "$ProjectDir\bilive-server.toml"
$env:BILIVE_VIDEOS_DIR = "$ProjectDir\Videos"
$env:BILIVE_DB_PATH = "$ProjectDir\src\db\data.db"
$env:BILIVE_COOKIE_FILE = "$ProjectDir\.secrets\bilibili.cookie"
if (-not $env:BILIVE_AUTO_UPLOAD) {
    $env:BILIVE_AUTO_UPLOAD = "1"
}

python -m uvicorn src.server.worker_api:api --host 127.0.0.1 --port 2235
