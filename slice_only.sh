#!/bin/bash
# 独立切片模式启动脚本
# 只切片不上传整场直播

# Set PYTHONPATH for imports
export PYTHONPATH=./src

# Create logs directory
mkdir -p ./logs/runtime

# kill the previous process
kill -9 $(ps aux | grep 'src.burn.scan' | grep -v grep | awk '{print $2}')
kill -9 $(ps aux | grep 'src.burn.scan_slice' | grep -v grep | awk '{print $2}')
kill -9 $(ps aux | grep '[u]pload' | awk '{print $2}')

# start slice-only scan (替代 render scan)
nohup python3 -m src.burn.scan_slice > ./logs/runtime/slice-$(date +%Y%m%d-%H%M%S).log 2>&1 &

# start upload (切片上传)
nohup python3 -m src.upload.upload > ./logs/runtime/upload-$(date +%Y%m%d-%H%M%S).log 2>&1 &

# Check if the last command was successful
if [ $? -eq 0 ]; then
    echo "Slice-only mode started! Please ignore the 'kill: usage....' if it displays"
else
    echo "An error occurred. Check the logs for details."
fi