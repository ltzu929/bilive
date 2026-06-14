# Manual Bilive Windows Worker API launcher.

param(
    [switch]$NoUpload
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectDir

$python = Join-Path $ProjectDir ".venv-win\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Windows environment missing: $python. Run setup_windows_env.ps1 first."
}

$arguments = @("-m", "src.server.worker_server", "--console")
if ($NoUpload) {
    $arguments += "--no-upload"
}

Write-Host "Bilive Worker API: http://127.0.0.1:2235"
Write-Host "Upload consumer is managed by the Worker API."
& $python @arguments
exit $LASTEXITCODE
