@echo off
set PYTHONPATH=D:\alldata\pi\bilive\src
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d D:\alldata\pi\bilive
python -m src.upload.upload >> logs\runtime\upload-daemon.log 2>&1
