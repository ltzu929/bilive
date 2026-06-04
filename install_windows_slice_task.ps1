# Register the manual Windows Scheduled Task used by the Pi dashboard trigger.

param(
    [string]$TaskName = "BiliveSliceOnce",
    [string]$ProjectDir = (Split-Path -Parent $MyInvocation.MyCommand.Path)
)

$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path -LiteralPath $ProjectDir).Path
$runScript = Join-Path $ProjectDir "run_slice_once.ps1"

if (-not (Test-Path -LiteralPath $runScript)) {
    throw "Cannot find run script: $runScript"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runScript`""

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 12) `
    -StartWhenAvailable:$false

$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Settings $settings `
    -Principal $principal `
    -Description "Run bilive pending slice queue once from the Pi dashboard trigger." `
    -Force | Out-Null

Write-Host "Registered scheduled task: $TaskName"
Write-Host "Test locally: schtasks /Run /TN $TaskName"
Write-Host "Test from Pi: ssh <windows-host> schtasks /Run /TN $TaskName"
