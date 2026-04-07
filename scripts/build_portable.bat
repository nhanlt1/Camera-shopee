@echo off
REM Đóng gói portable Windows (PyInstaller onedir) — copy cả thư mục dist\PackRecorder sang máy khác.
setlocal
cd /d "%~dp0.."
if not exist "src\packrecorder\__main__.py" (
  echo [LOI] Chay script tu trong repo Camera-shopee.
  pause
  exit /b 1
)

where py >nul 2>&1 && set "PY=py" || set "PY=python"
echo Dang cai packrecorder + PyInstaller ...
%PY% -m pip install -q -e "."
%PY% -m pip install -q "pyinstaller>=6.0"
if errorlevel 1 (
  echo [LOI] pip install that bai.
  pause
  exit /b 1
)
%PY% -m PyInstaller packrecorder.spec --noconfirm
if errorlevel 1 (
  echo [LOI] PyInstaller that bai.
  pause
  exit /b 1
)
echo.
echo Xong. Chay: dist\PackRecorder\PackRecorder.exe
echo Zip ca thu muc dist\PackRecorder de mang sang may khac (cung kien truc CPU, Windows 64-bit).
pause
