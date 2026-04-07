# Tao repo GitHub moi va push nhanh (can da: gh auth login)
# Vi du: .\scripts\github-first-push.ps1 -RepoName Camera-shopee
#        .\scripts\github-first-push.ps1 -RepoName packrecorder -Private

param(
    [string] $RepoName = "Camera-shopee",
    [switch] $Private
)

$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot ".."))

$null = gh auth status 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Chua dang nhap GitHub CLI. Chay: gh auth login" -ForegroundColor Yellow
    exit 1
}

if (git remote get-url origin 2>$null) {
    Write-Host "Remote 'origin' da ton tai. Xoa roi chay lai: git remote remove origin" -ForegroundColor Yellow
    exit 1
}

$vis = if ($Private) { "--private" } else { "--public" }
gh repo create $RepoName $vis --source . --remote origin --push --description "Pack Recorder - ghi video goi hang + quet ma"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Xong. Nhanh hien tai:" -ForegroundColor Green
git branch --show-current
