# Run database migration and start the local dashboard on 127.0.0.1:2234.

param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 2234,
    [string]$VideosDir = ""
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectDir
$Python = Join-Path $ProjectDir ".venv-win\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Windows environment missing: $Python. Run setup_windows_env.ps1 first."
}
$arguments = @(
    "-m", "src.server.dashboard_server",
    "--host", $HostAddress,
    "--port", $Port,
    "--console"
)
if ($VideosDir) { $arguments += @("--videos-dir", $VideosDir) }
& $Python @arguments
exit $LASTEXITCODE
