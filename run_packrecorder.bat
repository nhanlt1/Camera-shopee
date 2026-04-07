@echo off
REM Chay app trong phien Windows cua ban (khong gan voi terminal Cursor).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Chua co .venv. Mo PowerShell tai thu muc nay va chay:
  echo   python -m venv .venv
  echo   .venv\Scripts\pip install -e ".[dev]"
  pause
  exit /b 1
)
echo Kiem tra Pillow (chu tren video)...
".venv\Scripts\pip" install -q "pillow>=10.0.0" 2>nul
echo Dang mo Pack Recorder trong cua so rieng...
start "" /D "%~dp0" "%~dp0.venv\Scripts\python.exe" -m packrecorder
exit /b 0
