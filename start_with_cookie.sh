#!/bin/bash
# Auto sync cookie from bilitool and start blrec
# Usage: ./start_with_cookie.sh

set -e

# Get absolute path of project directory
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

# Activate virtual environment
source venv/bin/activate

# Stop existing blrec process
echo "Stopping existing blrec..."
kill -15 $(ps aux | grep '[b]lrec' | awk '{print $2}') 2>/dev/null || true
sleep 2

# Read cookie directly from bilitool config.json
CONFIG_FILE="./src/upload/bilitool/bilitool/model/config.json"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Config file not found: $CONFIG_FILE"
    exit 1
fi

# Extract cookies using Python (simpler than jq)
COOKIE=$(python -c "
import json
with open('$CONFIG_FILE') as f:
    config = json.load(f)
cookies = config['cookies']
if not cookies.get('SESSDATA'):
    print('')
else:
    print(f'SESSDATA={cookies[\"SESSDATA\"]}; bili_jct={cookies[\"bili_jct\"]}; DedeUserID={cookies[\"DedeUserID\"]}; DedeUserID__ckMd5={cookies[\"DedeUserID__ckMd5\"]}; sid={cookies[\"sid\"]}')
")

if [ -z "$COOKIE" ]; then
    echo "No cookie found! Please login first:"
    echo "  cd src/upload/bilitool && python -c 'from bilitool.cli import cli; cli()' login"
    exit 1
fi

echo "Found cookie, updating settings.toml..."

# Update settings.toml
sed -i "s|^cookie = .*|cookie = \"$COOKIE\"|" settings.toml
sed -i "s|^out_dir = .*|out_dir = \"./Videos\"|" settings.toml

# Do not use proxy
export no_proxy=*

# bind host and port
host=0.0.0.0
port=2233

# Start blrec
echo "Starting blrec..."
nohup blrec -c settings.toml --open --host $host --port $port --api-key "$RECORD_KEY" > ./logs/record/blrec-$(date +%Y%m%d-%H%M%S).log 2>&1 &

sleep 3

# Check if started
if ps aux | grep '[b]lrec' > /dev/null; then
    echo "Success! blrec is running."
    echo "Web UI: http://localhost:$port"

    # Show loaded tasks
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
    echo "Failed to start blrec. Check logs for details."
    exit 1
fi