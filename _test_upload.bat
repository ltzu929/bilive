@echo off
set PYTHONPATH=D:\alldata\pi\bilive\src
set PYTHONIOENCODING=utf-8
cd /d D:\alldata\pi\bilive
python -m src.upload.upload >> logs\runtime\upload-test.log 2>&1
