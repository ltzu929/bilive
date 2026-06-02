@echo off
set PYTHONPATH=D:\alldata\pi\bilive;D:\alldata\pi\bilive\src
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set BILIVE_CONFIG=D:\alldata\pi\bilive\bilive-server.toml
set BILIVE_VIDEOS_DIR=D:\alldata\pi\bilive\Videos
cd /d D:\alldata\pi\bilive
python -m src.server.watcher --once --videos-dir "%BILIVE_VIDEOS_DIR%" >> logs\runtime\pc-worker-test.log 2>&1
