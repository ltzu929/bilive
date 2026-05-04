#!/bin/bash
# Start slice-only scanning and uploader.

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

source venv/bin/activate
export PYTHONPATH=./src

mkdir -p ./logs/runtime ./logs/scan ./logs/upload

kill -9 $(ps aux | grep 'src.burn.scan' | grep -v grep | awk '{print $2}') 2>/dev/null || true
kill -9 $(ps aux | grep 'src.burn.scan_slice' | grep -v grep | awk '{print $2}') 2>/dev/null || true
kill -9 $(ps aux | grep '[u]pload' | awk '{print $2}') 2>/dev/null || true

nohup python -m src.burn.scan_slice > ./logs/runtime/slice-$(date +%Y%m%d-%H%M%S).log 2>&1 &
nohup python -m src.upload.upload > ./logs/runtime/upload-$(date +%Y%m%d-%H%M%S).log 2>&1 &

echo "Slice-only pipeline started."
echo "Logs: ./logs/runtime"
