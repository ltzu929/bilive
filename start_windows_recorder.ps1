# Start the local Windows blrec service on 127.0.0.1:2233.

param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 2233,
    [string]$VideosDir = ""
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectDir
$Python = Join-Path $ProjectDir ".venv-recorder\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Recorder environment missing: $Python. Run setup_windows_recorder_env.ps1 first."
}
$arguments = @(
    "-m", "src.server.recorder_server",
    "--host", $HostAddress,
    "--port", $Port,
    "--console"
)
if ($VideosDir) { $arguments += @("--videos-dir", $VideosDir) }
& $Python @arguments
exit $LASTEXITCODE
