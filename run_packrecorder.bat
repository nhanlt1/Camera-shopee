@echo off
REM Chay app trong phien Windows cua ban (khong gan voi terminal Cursor).
REM Dung pythonw (khong mo cua so den). python.exe + start = thuong co cua so CMD nhap nhay —
REM de bi dong / nham la app da tat.
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
echo Kiem tra hidapi (may quyet HID POS, co DLL Windows)...
".venv\Scripts\pip" install -q "hidapi>=0.14.0" 2>nul
echo Dang mo Pack Recorder...
REM Neu van crash: thu run_packrecorder_no_mp.bat (tat pipeline multiprocessing).
REM Tieu de khac rong: mot so phien Windows xu start "" ... kem.
if exist ".venv\Scripts\pythonw.exe" (
  start "Pack Recorder" /D "%~dp0" "%~dp0.venv\Scripts\pythonw.exe" -m packrecorder
) else (
  start "Pack Recorder" /D "%~dp0" "%~dp0.venv\Scripts\python.exe" -m packrecorder
)
echo.
echo Neu cua so app khong hien hoac tat ngay: mo CMD tai thu muc nay, chay:
echo   .venv\Scripts\python.exe -m packrecorder
echo de xem loi tren man hinh den.
exit /b 0
