param(
    [switch]$Recreate
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ProjectDir ".venv-win"
$Python = Join-Path $VenvDir "Scripts\python.exe"
$Requirements = Join-Path $ProjectDir "requirements\windows.txt"

if ($Recreate -and (Test-Path -LiteralPath $VenvDir)) {
    Remove-Item -LiteralPath $VenvDir -Recurse -Force
}

if (-not (Test-Path -LiteralPath $Python)) {
    & py -3.13 -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create $VenvDir with Python 3.13"
    }
}

& $Python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Failed to upgrade pip"
}

& $Python -m pip install --requirement $Requirements
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install Windows dependencies"
}

& $Python -m pip check
if ($LASTEXITCODE -ne 0) {
    throw "Windows environment contains dependency conflicts"
}

Write-Host "Windows environment ready: $Python"
