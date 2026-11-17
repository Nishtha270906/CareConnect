@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Virtual environment not found. Please run run.bat once first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe seed_demo_data.py
pause
