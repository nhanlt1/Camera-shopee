@echo off
REM Pack Recorder — khoi dong tach khoi CMD (dong cua so nay KHONG tat app).
REM Truoc day Python gan vao cung cua so CMD: dong CMD = tat app ngay — rat de nham.
title Pack Recorder — launcher
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [LOI] Chua co .venv
  echo Chay: python -m venv .venv
  echo Sau do: .venv\Scripts\pip install -e ".[dev]"
  pause
  exit /b 1
)
echo Kiem tra Pillow (chu tren video, khuyen nghi)...
".venv\Scripts\pip" install -q "pillow>=10.0.0"
echo Kiem tra hidapi (may quyet HID POS, co DLL Windows)...
".venv\Scripts\pip" install -q "hidapi>=0.14.0"
if errorlevel 1 (
  echo [CANH BAO] Khong cai duoc pillow — app van chay, chu tren video dung font don gian.
  echo Thu tay: .venv\Scripts\pip install -e ".\[dev]"
)
REM Webcam USB khong mo (cam 0): thu bo dong duoi — DirectShow truoc MSMF.
REM set PACKRECORDER_PREFER_DSHOW=1
REM Neu driver loi khi doc thu khung: set PACKRECORDER_SKIP_CAPTURE_VALIDATE=1
REM pythonw = khong cua so console — process doc lap; dong CMD nay khong lam tat app.
if exist ".venv\Scripts\pythonw.exe" (
  echo Dang mo Pack Recorder (tach khoi cua so nay)...
  start "Pack Recorder" /D "%~dp0" "%~dp0.venv\Scripts\pythonw.exe" -m packrecorder
) else (
  echo Dang mo Pack Recorder (cua so Python rieng)...
  start "Pack Recorder" /D "%~dp0" "%~dp0.venv\Scripts\python.exe" -m packrecorder
)
echo.
echo Da gui lenh khoi dong. Ban co the DONG cua so CMD nay — app van chay neu da bat duoc.
echo Log: %LOCALAPPDATA%\PackRecorder\ hoac run_errors.log trong thu muc project.
echo Neu can xem loi trong console: chay truc tiep:
echo   .venv\Scripts\python.exe -m packrecorder
echo.
pause
