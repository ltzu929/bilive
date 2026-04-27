@echo off
cd /d %~dp0

taskkill /f /im python.exe /fi "WINDOWTITLE eq blrec*" 2>nul
taskkill /f /im python.exe /fi "WINDOWTITLE eq scan*" 2>nul
taskkill /f /im python.exe /fi "WINDOWTITLE eq upload*" 2>nul

start "blrec" /min python -m blrec -c settings.toml --open --host 0.0.0.0 --port 2233
start "scan" /min python -m src.burn.scan
start "upload" /min python -m src.upload.upload

echo Done.
pause