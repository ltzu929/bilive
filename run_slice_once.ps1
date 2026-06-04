# Run the pending slice queue once and keep this process alive until it exits.
# This script is intended to be the Windows Scheduled Task action.

param(
    [string]$ProjectDir = (Split-Path -Parent $MyInvocation.MyCommand.Path)
)

$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path -LiteralPath $ProjectDir).Path
Set-Location -LiteralPath $ProjectDir

$env:PYTHONPATH = "$ProjectDir;$ProjectDir\src"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:BILIVE_CONFIG = "$ProjectDir\bilive-server.toml"
$env:BILIVE_VIDEOS_DIR = "$ProjectDir\Videos"

$logDir = Join-Path $ProjectDir "logs\runtime"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$lockPath = Join-Path $logDir "slice-once.lock"
$dateSuffix = Get-Date -Format "yyyyMMdd-HHmmss"
$logPath = Join-Path $logDir "pc-worker-task-$dateSuffix.log"
$errPath = Join-Path $logDir "pc-worker-task-$dateSuffix.err"

if (Test-Path -LiteralPath $lockPath) {
    $lock = Get-Item -LiteralPath $lockPath
    if (((Get-Date) - $lock.LastWriteTime).TotalHours -gt 12) {
        Remove-Item -LiteralPath $lockPath -Force
    }
}

$lockStream = $null
try {
    $lockStream = [System.IO.File]::Open(
        $lockPath,
        [System.IO.FileMode]::CreateNew,
        [System.IO.FileAccess]::Write,
        [System.IO.FileShare]::None
    )
} catch [System.IO.IOException] {
    Write-Host "A slice worker is already running. Lock: $lockPath"
    exit 0
}

try {
    $lockBytes = [System.Text.Encoding]::UTF8.GetBytes("$PID $dateSuffix")
    $lockStream.Write($lockBytes, 0, $lockBytes.Length)
    $lockStream.Flush()

    $python = (Get-Command python.exe -ErrorAction Stop).Source
    $proc = Start-Process -FilePath $python `
        -ArgumentList @("-m", "src.server.watcher", "--once", "--videos-dir", "$env:BILIVE_VIDEOS_DIR") `
        -WorkingDirectory $ProjectDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $logPath `
        -RedirectStandardError $errPath `
        -Wait `
        -PassThru

    Write-Host "Pending slice worker exited with code $($proc.ExitCode)."
    Write-Host "Log: $logPath"
    Write-Host "Err: $errPath"
    exit $proc.ExitCode
} finally {
    if ($lockStream) {
        $lockStream.Dispose()
    }
    Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
}
