@echo off
set PYTHONPATH=D:\alldata\pi\bilive\src
set PYTHONIOENCODING=utf-8
cd /d D:\alldata\pi\bilive
python -m src.burn.scan_slice >> logs\runtime\slice-test.log 2>&1
