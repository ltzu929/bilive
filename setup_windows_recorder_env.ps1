# Create the isolated legacy-compatible Windows recorder environment.

param(
    [switch]$Recreate,
    [switch]$UpgradePip,
    [string]$PythonVersion = "3.10"
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ProjectDir ".venv-recorder"
$Python = Join-Path $VenvDir "Scripts\python.exe"
$Requirements = Join-Path $ProjectDir "requirements\recorder-windows.txt"
$BlrecWheel = Join-Path $ProjectDir "wheel\blrec-2.0.0b4-py3-none-any.whl"
$Settings = Join-Path $ProjectDir "settings.toml"
$SettingsTemplate = Join-Path $ProjectDir "settings.example.toml"

if ($Recreate -and (Test-Path -LiteralPath $VenvDir)) {
    Remove-Item -LiteralPath $VenvDir -Recurse -Force
}

if (-not (Test-Path -LiteralPath $Python)) {
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uv) {
        throw "uv is required to provision Python $PythonVersion for the legacy blrec environment."
    }
    & $uv.Source venv --python $PythonVersion --seed $VenvDir
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create $VenvDir with Python $PythonVersion"
    }
}

if ($UpgradePip) {
    & $Python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "Failed to upgrade recorder pip" }
}

& $Python -m pip install $BlrecWheel --requirement $Requirements
if ($LASTEXITCODE -ne 0) { throw "Failed to install recorder dependencies" }

if (-not (Test-Path -LiteralPath $Settings)) {
    if (-not (Test-Path -LiteralPath $SettingsTemplate)) {
        throw "Recorder settings template missing: $SettingsTemplate"
    }
    Copy-Item -LiteralPath $SettingsTemplate -Destination $Settings
    Write-Host "Created machine-local settings.toml from settings.example.toml"
}
New-Item -ItemType Directory -Force -Path `
    (Join-Path $ProjectDir "Videos"), `
    (Join-Path $ProjectDir "logs\record") | Out-Null

Push-Location -LiteralPath $ProjectDir
try {
    & $Python -m src.blrec_patch
    if ($LASTEXITCODE -ne 0) { throw "Failed to apply the blrec FPS guard" }
    & $Python -m src.blrec_settings $Settings
    if ($LASTEXITCODE -ne 0) { throw "Failed to validate blrec settings" }
    & $Python -m pip check
    if ($LASTEXITCODE -ne 0) { throw "Recorder environment contains dependency conflicts" }
} finally {
    Pop-Location
}

Write-Host "Recorder environment ready: $Python"
