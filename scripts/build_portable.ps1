# Đóng gói portable (PyInstaller). Chạy từ PowerShell tại thư mục repo:
#   .\scripts\build_portable.ps1
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not (Test-Path "src/packrecorder/__main__.py")) {
    throw "Chạy script trong repo packrecorder."
}
$py = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }
& $py -m pip install -q -e "."
& $py -m pip install -q "pyinstaller>=6.0"
& $py -m PyInstaller packrecorder.spec --noconfirm
Write-Host "Xong: dist\PackRecorder\PackRecorder.exe"
