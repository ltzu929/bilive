param(
    [switch]$Recreate,
    [switch]$Dev,
    [switch]$UpgradePip,
    [switch]$SkipLlamaRuntime
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ProjectDir ".venv-win"
$Python = Join-Path $VenvDir "Scripts\python.exe"
$Requirements = Join-Path $ProjectDir "requirements\windows.txt"
$DevRequirements = Join-Path $ProjectDir "requirements\dev.txt"

if ($Recreate -and (Test-Path -LiteralPath $VenvDir)) {
    Remove-Item -LiteralPath $VenvDir -Recurse -Force
}

if (-not (Test-Path -LiteralPath $Python)) {
    & py -3.13 -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create $VenvDir with Python 3.13"
    }
}

if ($UpgradePip) {
    & $Python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to upgrade pip"
    }
}

& $Python -m pip install --requirement $Requirements
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install Windows dependencies"
}
if ($Dev) {
    & $Python -m pip install --requirement $DevRequirements
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install Windows development dependencies"
    }
}

& $Python -m pip check
if ($LASTEXITCODE -ne 0) {
    throw "Windows environment contains dependency conflicts"
}

if (-not $SkipLlamaRuntime) {
    & (Join-Path $ProjectDir "install_llama_runtime.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install the managed llama.cpp runtime"
    }
}

Write-Host "Windows environment ready: $Python"
