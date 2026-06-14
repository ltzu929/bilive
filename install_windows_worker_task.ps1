# Register the hidden on-demand Worker API and remove the legacy one-shot task.

param(
    [string]$TaskName = "BiliveWorkerApi",
    [string]$ProjectDir = (Split-Path -Parent $MyInvocation.MyCommand.Path),
    [switch]$NoUpload,
    [switch]$EnableUpload,
    [int]$VerifyTimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path -LiteralPath $ProjectDir).Path
$pythonw = Join-Path $ProjectDir ".venv-win\Scripts\pythonw.exe"

if (-not (Test-Path -LiteralPath $pythonw)) {
    throw "Cannot find hidden Python launcher: $pythonw"
}
if ($NoUpload -and $EnableUpload) {
    throw "Use either -NoUpload or -EnableUpload, not both."
}

$workerArguments = "-m src.server.worker_server"
if (-not $EnableUpload) {
    $workerArguments += " --no-upload"
}

$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existingTask -and $existingTask.State -eq "Running") {
    Stop-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 1
}

$existingListener = Get-NetTCPConnection `
    -LocalAddress "127.0.0.1" `
    -LocalPort 2235 `
    -State Listen `
    -ErrorAction SilentlyContinue
if ($existingListener) {
    $ownerPid = [int]$existingListener[0].OwningProcess
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerPid"
    $expectedPython = Join-Path $ProjectDir ".venv-win\Scripts\python.exe"
    $expectedPythonw = Join-Path $ProjectDir ".venv-win\Scripts\pythonw.exe"
    $ownedByProject = (
        $owner.CommandLine -and
        (
            $owner.CommandLine.Contains($expectedPython) -or
            $owner.CommandLine.Contains($expectedPythonw)
        ) -and
        (
            $owner.CommandLine.Contains("src.server.worker_server") -or
            $owner.CommandLine.Contains("src.server.worker_api:api")
        )
    )
    if (-not $ownedByProject) {
        throw "Port 2235 is occupied by a process not owned by this project"
    }
    Stop-Process -Id $ownerPid -Force
    $portReleaseDeadline = (Get-Date).AddSeconds($VerifyTimeoutSeconds)
    do {
        Start-Sleep -Milliseconds 500
        $existingListener = Get-NetTCPConnection `
            -LocalAddress "127.0.0.1" `
            -LocalPort 2235 `
            -State Listen `
            -ErrorAction SilentlyContinue
    } while ($existingListener -and (Get-Date) -lt $portReleaseDeadline)
    if ($existingListener) {
        throw "Existing BiliveWorkerApi did not release port 2235"
    }
}
$listenerBeforeStart = $ownerPid

$action = New-ScheduledTaskAction `
    -Execute $pythonw `
    -Argument $workerArguments `
    -WorkingDirectory $ProjectDir
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
    -Settings $settings `
    -Principal $principal `
    -Description "On-demand hidden bilive Windows Worker API and upload consumer." `
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
    if (
        $task.State -eq "Running" -and
        $listener -and
        $listener.OwningProcess -ne $listenerBeforeStart
    ) {
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
