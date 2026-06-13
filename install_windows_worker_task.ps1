# Register the always-on Worker API at user logon and remove the legacy one-shot task.

param(
    [string]$TaskName = "BiliveWorkerApi",
    [string]$ProjectDir = (Split-Path -Parent $MyInvocation.MyCommand.Path),
    [switch]$NoLMStudio,
    [switch]$NoUpload,
    [switch]$EnableUpload,
    [string]$LMStudioPath = $env:BILIVE_LM_STUDIO_PATH,
    [int]$VerifyTimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path -LiteralPath $ProjectDir).Path
$runScript = Join-Path $ProjectDir "start_pipeline.ps1"

if (-not (Test-Path -LiteralPath $runScript)) {
    throw "Cannot find Worker API launcher: $runScript"
}
if ($NoUpload -and $EnableUpload) {
    throw "Use either -NoUpload or -EnableUpload, not both."
}

$pipelineArguments = ""
if ($NoLMStudio) {
    $pipelineArguments += " -NoLMStudio"
}
if (-not $EnableUpload) {
    $pipelineArguments += " -NoUpload"
}
if ($LMStudioPath) {
    $pipelineArguments += " -LMStudioPath `"$LMStudioPath`""
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runScript`"$pipelineArguments"
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

$deadline = (Get-Date).AddSeconds($VerifyTimeoutSeconds)
$status = $null
do {
    Start-Sleep -Seconds 1
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
    $listener = Get-NetTCPConnection `
        -LocalAddress "127.0.0.1" `
        -LocalPort 2235 `
        -State Listen `
        -ErrorAction SilentlyContinue
    if ($task.State -eq "Running" -and $listener) {
        try {
            $status = Invoke-RestMethod `
                -Uri "http://127.0.0.1:2235/api/worker/status" `
                -TimeoutSec 3
        } catch {
            $status = $null
        }
    }
} while (-not $status -and (Get-Date) -lt $deadline)

if (-not $status) {
    throw (
        "BiliveWorkerApi verification failed. " +
        "TaskState=$($task.State), LastTaskResult=$($taskInfo.LastTaskResult), " +
        "Port2235Listening=$([bool]$listener)"
    )
}

Write-Host "Registered and verified scheduled task: $TaskName"
Write-Host "Upload enabled: $EnableUpload"
$status | ConvertTo-Json -Depth 8
