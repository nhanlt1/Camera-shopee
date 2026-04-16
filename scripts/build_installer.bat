@echo off
REM Build Windows installer (.exe) by Inno Setup.
setlocal
cd /d "%~dp0.."

if not exist "installer\PackRecorder.iss" (
  echo [LOI] Khong tim thay installer\PackRecorder.iss
  exit /b 1
)

where py >nul 2>&1 && set "PY=py" || set "PY=python"

set "APP_VERSION=0.1.0"
for /f %%v in ('%PY% -c "import pathlib, tomllib;print(tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8'))['project']['version'])"') do set "APP_VERSION=%%v"

set "SRC_DIR=dist\PackRecorder"
if not exist "%SRC_DIR%\PackRecorder.exe" (
  if exist "dist_fresh\PackRecorder\PackRecorder.exe" (
    set "SRC_DIR=dist_fresh\PackRecorder"
  ) else (
    echo [INFO] Chua co ban portable, dang build qua PyInstaller...
    %PY% -m pip install -q -e "."
    %PY% -m pip install -q "pyinstaller>=6.0"
    %PY% -m PyInstaller packrecorder.spec --noconfirm --distpath dist_fresh
    if errorlevel 1 (
      echo [LOI] Build portable that bai.
      exit /b 1
    )
    set "SRC_DIR=dist_fresh\PackRecorder"
  )
)

set "ISCC_EXE="
for /f "delims=" %%i in ('where iscc 2^>nul') do set "ISCC_EXE=%%i"
if not defined ISCC_EXE if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC_EXE if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC_EXE if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC_EXE=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC_EXE (
  echo [LOI] Chua tim thay ISCC.exe. Cai Inno Setup 6 roi chay lai.
  exit /b 1
)

echo [INFO] Dung source: %SRC_DIR%
echo [INFO] App version: %APP_VERSION%
set "SRC_DIR_ABS=%CD%\%SRC_DIR%"
"%ISCC_EXE%" "/DAppVersion=%APP_VERSION%" "/DSourceDir=%SRC_DIR_ABS%" "installer\PackRecorder.iss"
if errorlevel 1 (
  echo [LOI] Tao installer that bai.
  exit /b 1
)

echo.
echo [OK] Installer: dist-installer\PackRecorder-Setup-%APP_VERSION%.exe
