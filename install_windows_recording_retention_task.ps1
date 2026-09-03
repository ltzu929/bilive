# Register the daily Windows source-recording retention pass.

param(
    [string]$TaskName = "BiliveRecordingRetention",
    [string]$ProjectDir = (Split-Path -Parent $MyInvocation.MyCommand.Path),
    [string]$At = "03:00",
    [switch]$StartNow
)

$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path -LiteralPath $ProjectDir).Path
$pythonw = Join-Path $ProjectDir ".venv-win\Scripts\pythonw.exe"
$videosRoot = Join-Path $ProjectDir "Videos"

if (-not (Test-Path -LiteralPath $pythonw)) {
    throw "Cannot find hidden Python launcher: $pythonw"
}

$action = New-ScheduledTaskAction `
    -Execute $pythonw `
    -Argument "-m src.maintenance.recording_retention --videos-root `"$videosRoot`"" `
    -WorkingDirectory $ProjectDir
$trigger = New-ScheduledTaskTrigger -Daily -At ([datetime]::Parse($At))
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Daily bilive source-recording retention and Recycle Bin maintenance." `
    -Force | Out-Null

if ($StartNow) {
    Start-ScheduledTask -TaskName $TaskName
}

Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State, Triggers, Actions
