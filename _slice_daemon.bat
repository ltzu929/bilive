@echo off
set PYTHONPATH=D:\alldata\pi\bilive\src
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d D:\alldata\pi\bilive
python -m src.burn.scan_slice >> logs\runtime\slice-daemon.log 2>&1
