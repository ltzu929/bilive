#!/bin/bash
# record-pi.sh — 在树莓派上启动 blrec 录制
#
# 与 record.sh 的区别:
#   1. out_dir 指向 NFS 挂载路径（而非 ./Videos）
#   2. cookie 和日志也写到 NFS
#   3. 使用 Pi 端轻量 venv
#
# 环境变量:
#   BILIVE_RUNTIME_DIR  — 项目根目录 (默认: 脚本所在目录)
#   BILIVE_VENV_DIR     — Python venv 路径 (默认: ./venv)
#   BILIVE_VIDEOS_DIR   — 视频输出目录 (默认: /mnt/bilive/Videos)
#   BILIVE_LOG_DIR      — 日志目录 (默认: /mnt/bilive/logs)
#   RECORD_KEY          — blrec API 密钥 (必须)
#   BLREC_HOST          — blrec 监听地址 (默认: 0.0.0.0)
#   BLREC_PORT          — blrec 监听端口 (默认: 2233)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="${BILIVE_RUNTIME_DIR:-$SCRIPT_DIR}"
cd "$PROJECT_DIR"

# ── NFS 挂载路径 ──
VIDEOS_DIR="${BILIVE_VIDEOS_DIR:-/mnt/bilive/Videos}"
LOG_DIR="${BILIVE_LOG_DIR:-/mnt/bilive/logs}"

mkdir -p "$VIDEOS_DIR" "$LOG_DIR/record"

# ── 激活 Python 环境：优先 conda，回退 venv ──
CONDA_SH="$HOME/miniforge/etc/profile.d/conda.sh"
if [ -f "$CONDA_SH" ]; then
    source "$CONDA_SH" && conda activate bilive
else
    VENV_DIR="${BILIVE_VENV_DIR:-$PROJECT_DIR/venv}"
    if [ -f "$VENV_DIR/bin/activate" ]; then
        source "$VENV_DIR/bin/activate"
    else
        echo "No Python environment found. Install conda or create venv."
        exit 1
    fi
fi

# ── 检查 RECORD_KEY ──
if [ -z "$RECORD_KEY" ] || [ ${#RECORD_KEY} -lt 8 ] || [ ${#RECORD_KEY} -gt 80 ]; then
    echo "RECORD_KEY must be 8-80 characters. Set it before starting:"
    echo "  export RECORD_KEY=your_record_password"
    exit 1
fi

# ── Cookie 处理 ──
COOKIE_STORE="${BILIVE_COOKIE_FILE:-/mnt/bilive/.secrets/bilibili.cookie}"
export COOKIE_STORE

COOKIE=$(python - <<'PY'
import json
import os
import re
from pathlib import Path

def format_cookie(cookies):
    if not isinstance(cookies, dict) or not cookies.get("SESSDATA"):
        return ""
    ordered_keys = ["SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid"]
    parts = [f"{key}={cookies[key]}" for key in ordered_keys if cookies.get(key)]
    return "; ".join(parts)

def read_json_cookie(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    cookie = format_cookie(data.get("cookies", data))
    if cookie:
        return cookie
    if isinstance(data.get("cookie"), str):
        return data["cookie"].strip()
    return ""

def read_raw_cookie(path):
    try:
        cookie = path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
    return cookie if "SESSDATA=" in cookie else ""

cookie_store = Path(os.environ.get("COOKIE_STORE", "/mnt/bilive/.secrets/bilibili.cookie"))

for candidate in [
    Path("src/upload/bilitool/bilitool/model/config.json"),
    Path("cookie.json"),
    Path("cookies.json"),
    cookie_store,
]:
    if candidate.is_file():
        cookie = read_json_cookie(candidate) if candidate.suffix == ".json" else read_raw_cookie(candidate)
        if cookie:
            print(cookie)
            raise SystemExit(0)

settings_path = Path("settings.toml")
if settings_path.is_file():
    text = settings_path.read_text(encoding="utf-8")
    match = re.search(r'^\s*cookie\s*=\s*"(.*)"\s*$', text, re.MULTILINE)
    if match and match.group(1).strip():
        print(match.group(1).strip())
PY
)

if [ -z "$COOKIE" ]; then
    echo "No cookie found. Please login first:"
    echo "  cd src/upload/bilitool && python -m bilitool.cli login"
    exit 1
fi

echo "Found cookie, updating local recorder config..."
mkdir -p "$(dirname "$COOKIE_STORE")" "$LOG_DIR/record"
printf '%s\n' "$COOKIE" > "$COOKIE_STORE"
chmod 600 "$COOKIE_STORE" 2>/dev/null || true

# ── 更新 settings.toml 的 cookie 和 out_dir ──
export COOKIE
python - <<PY
import json
import os
import re
from pathlib import Path

settings_path = Path("settings.toml")
if not settings_path.is_file():
    raise SystemExit("settings.toml not found.")

cookie = os.environ["COOKIE"]
videos_dir = os.environ.get("BILIVE_VIDEOS_DIR", "/mnt/bilive/Videos")
text = settings_path.read_text(encoding="utf-8")

if not re.search(r'^\s*cookie\s*=', text, re.MULTILINE):
    raise SystemExit("settings.toml does not contain a cookie entry.")

# 更新 cookie
text = re.sub(
    r'^\s*cookie\s*=.*$',
    f"cookie = {json.dumps(cookie, ensure_ascii=False)}",
    text,
    flags=re.MULTILINE,
)

# 更新 out_dir 指向 NFS 挂载路径
text = re.sub(
    r'^\s*out_dir\s*=.*$',
    f'out_dir = "{videos_dir}"',
    text,
    flags=re.MULTILINE,
)

settings_path.write_text(text, encoding="utf-8")
PY

# ── 停止旧 blrec ──
echo "Stopping existing blrec..."
while IFS= read -r pid; do
    [ -n "$pid" ] || continue
    [ "$pid" = "$$" ] && continue
    process_cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"
    if [ "$process_cwd" = "$PROJECT_DIR" ]; then
        kill -15 "$pid" 2>/dev/null || true
    fi
done < <(pgrep -f '[b]lrec' 2>/dev/null || true)
sleep 2

# ── 启动 blrec ──
export no_proxy=*
host="${BLREC_HOST:-0.0.0.0}"
port="${BLREC_PORT:-2233}"

echo "Starting blrec (output to NFS: $VIDEOS_DIR)..."
nohup blrec -c settings.toml --host "$host" --port "$port" --api-key "$RECORD_KEY" > "$LOG_DIR/record/blrec-$(date +%Y%m%d-%H%M%S).log" 2>&1 &
sleep 3

if python - "$port" <<'PY'
import socket
import sys
port = int(sys.argv[1])
with socket.create_connection(("127.0.0.1", port), timeout=2):
    pass
PY
then
    echo "Success! blrec is running."
    echo "Web UI: http://localhost:$port"
    echo "Output: $VIDEOS_DIR"
else
    echo "Failed to start blrec. Check $LOG_DIR/record for details."
    exit 1
fi