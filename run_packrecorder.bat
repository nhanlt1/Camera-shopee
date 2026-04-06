@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Chua co .venv — chay: python -m venv .venv ^& .venv\Scripts\pip install -e ".[dev]"
  pause
  exit /b 1
)
echo Dang mo Pack Recorder...
".venv\Scripts\python.exe" -m packrecorder
if errorlevel 1 pause
