@echo off
REM Chay Pack Recorder KHONG dung pipeline multiprocessing (camera + shared memory).
REM Dung khi bi crash native / tat ngay — luong quay lai ScanWorker trong process.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Chua co .venv — xem run_packrecorder.bat
  pause
  exit /b 1
)
set PACKRECORDER_DISABLE_MP=1
echo PACKRECORDER_DISABLE_MP=1 (camera trong thread, khong process phu)
if exist ".venv\Scripts\pythonw.exe" (
  start "Pack Recorder" /D "%~dp0" "%~dp0.venv\Scripts\pythonw.exe" -m packrecorder
) else (
  start "Pack Recorder" /D "%~dp0" "%~dp0.venv\Scripts\python.exe" -m packrecorder
)
exit /b 0
