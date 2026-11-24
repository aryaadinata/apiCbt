@echo off
title CBT Microservice API - Port 5005
color 0B
echo ===================================================================
echo     MENJALANKAN API CBT SERVICE (PORT 5005)
echo ===================================================================
cd /d "%~dp0"
if exist "..\apiNextSiak\venv\Scripts\python.exe" (
    "..\apiNextSiak\venv\Scripts\python.exe" main.py
) else (
    python main.py
)
pause
