#!/bin/bash
# Start blrec with a persisted Bilibili cookie.

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

source venv/bin/activate

if [ ${#RECORD_KEY} -lt 8 ] || [ ${#RECORD_KEY} -gt 80 ]; then
    echo "RECORD_KEY must be 8-80 characters. Set it before starting:"
    echo "  export RECORD_KEY=your_record_password"
    exit 1
fi

COOKIE_STORE="${BILIVE_COOKIE_FILE:-.secrets/bilibili.cookie}"
export COOKIE_STORE

COOKIE=$(python - <<'PY'
import json
import os
import re
from pathlib import Path


def format_cookie(cookies):
    if not isinstance(cookies, dict) or not cookies.get("SESSDATA"):
        return ""

    ordered_keys = [
        "SESSDATA",
        "bili_jct",
        "DedeUserID",
        "DedeUserID__ckMd5",
        "sid",
    ]
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


cookie_store = Path(os.environ.get("COOKIE_STORE", ".secrets/bilibili.cookie"))

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
mkdir -p "$(dirname "$COOKIE_STORE")" ./logs/record
printf '%s\n' "$COOKIE" > "$COOKIE_STORE"
chmod 600 "$COOKIE_STORE" 2>/dev/null || true

export COOKIE
python - <<'PY'
import json
import os
import re
from pathlib import Path


settings_path = Path("settings.toml")
if not settings_path.is_file():
    raise SystemExit("settings.toml not found. Restore your local recorder config first.")

cookie = os.environ["COOKIE"]
text = settings_path.read_text(encoding="utf-8")

if not re.search(r'^\s*cookie\s*=', text, re.MULTILINE):
    raise SystemExit("settings.toml does not contain a cookie entry.")

text = re.sub(
    r'^\s*cookie\s*=.*$',
    f"cookie = {json.dumps(cookie, ensure_ascii=False)}",
    text,
    flags=re.MULTILINE,
)
text = re.sub(
    r'^\s*out_dir\s*=.*$',
    'out_dir = "./Videos"',
    text,
    flags=re.MULTILINE,
)
settings_path.write_text(text, encoding="utf-8")
PY

echo "Stopping existing blrec..."
kill -15 $(ps aux | grep '[b]lrec' | awk '{print $2}') 2>/dev/null || true
sleep 2

export no_proxy=*
host=0.0.0.0
port=2233

echo "Starting blrec..."
nohup blrec -c settings.toml --host $host --port $port --api-key "$RECORD_KEY" > ./logs/record/blrec-$(date +%Y%m%d-%H%M%S).log 2>&1 &
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
    echo ""
    echo "Loaded rooms:"
    curl -s -H "X-API-Key: $RECORD_KEY" http://localhost:$port/api/v1/tasks/data 2>/dev/null | python -c "
import json, sys
try:
    data = json.load(sys.stdin)
    for d in data:
        print(f'  - {d[\"room_info\"][\"room_id\"]} ({d[\"user_info\"][\"name\"]})')
except:
    print('  (waiting for tasks to load...)')
" || true
else
    echo "Failed to start blrec or port $port is not listening. Check logs/record for details."
    exit 1
fi
