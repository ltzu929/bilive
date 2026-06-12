# Register the always-on Worker API at user logon and remove the legacy one-shot task.

param(
    [string]$TaskName = "BiliveWorkerApi",
    [string]$ProjectDir = (Split-Path -Parent $MyInvocation.MyCommand.Path)
)

$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path -LiteralPath $ProjectDir).Path
$runScript = Join-Path $ProjectDir "start_pipeline.ps1"

if (-not (Test-Path -LiteralPath $runScript)) {
    throw "Cannot find Worker API launcher: $runScript"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runScript`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)
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
    -Description "Always-on bilive Windows Worker API and upload consumer." `
    -Force | Out-Null

if (Get-ScheduledTask -TaskName "BiliveSliceOnce" -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName "BiliveSliceOnce" -Confirm:$false
}

Start-ScheduledTask -TaskName $TaskName
Write-Host "Registered and started scheduled task: $TaskName"
