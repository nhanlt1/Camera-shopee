@echo off
REM Mo CMD de xem loi neu app khong hien hoac tat ngay.
title Pack Recorder — console
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
if errorlevel 1 (
  echo [CANH BAO] Khong cai duoc pillow — app van chay, chu tren video dung font don gian.
  echo Thu tay: .venv\Scripts\pip install -e ".\[dev]"
)
echo Chay ung dung — neu co loi se hien ben duoi.
echo Dong cua so nay se tat ung dung.
echo.
".venv\Scripts\python.exe" -m packrecorder
echo.
echo Ma thoat: %ERRORLEVEL%
pause
