# Register Recorder and Dashboard to start when the current user logs on.

param(
    [string]$ProjectDir = (Split-Path -Parent $MyInvocation.MyCommand.Path),
    [switch]$StartNow,
    [switch]$NoRecorder,
    [switch]$NoDashboard
)

$ErrorActionPreference = "Stop"
if ($NoRecorder -and $NoDashboard) {
    throw "At least one of Recorder or Dashboard must be enabled."
}
$ProjectDir = (Resolve-Path -LiteralPath $ProjectDir).Path
$UserId = [Security.Principal.WindowsIdentity]::GetCurrent().Name

function Register-BiliveLogonTask {
    param(
        [string]$TaskName,
        [string]$PythonExe,
        [string]$ModuleName,
        [int]$Port,
        [string]$Description
    )
    if (-not (Test-Path -LiteralPath $PythonExe)) {
        throw "Cannot find hidden Python launcher: $PythonExe"
    }
    $existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existingTask -and $existingTask.State -eq "Running") {
        Stop-ScheduledTask -TaskName $TaskName
        Start-Sleep -Seconds 1
    }
    $listener = Get-NetTCPConnection `
        -LocalAddress "127.0.0.1" `
        -LocalPort $Port `
        -State Listen `
        -ErrorAction SilentlyContinue
    if ($listener) {
        $ownerPid = [int]$listener[0].OwningProcess
        $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerPid"
        $ownedByProject = (
            $owner.CommandLine -and
            $owner.CommandLine.Contains($ProjectDir) -and
            (
                $owner.CommandLine.Contains($ModuleName) -or
                $owner.CommandLine.Contains("start_windows_recorder.ps1") -or
                $owner.CommandLine.Contains("start_windows_dashboard.ps1") -or
                $owner.CommandLine.Contains("-m blrec") -or
                $owner.CommandLine.Contains("src.dashboard.app:api")
            )
        )
        if (-not $ownedByProject) {
            throw "Port $Port is occupied by a process not owned by this project"
        }
        Stop-Process -Id $ownerPid -Force
    }
    $action = New-ScheduledTaskAction `
        -Execute $PythonExe `
        -Argument "-m $ModuleName" `
        -WorkingDirectory $ProjectDir
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $UserId
    $settings = New-ScheduledTaskSettingsSet `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1)
    $principal = New-ScheduledTaskPrincipal `
        -UserId $UserId `
        -LogonType Interactive `
        -RunLevel Limited
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description $Description `
        -Force | Out-Null
    if ($StartNow) { Start-ScheduledTask -TaskName $TaskName }
}

$registeredTasks = @()
if (-not $NoRecorder) {
    Register-BiliveLogonTask `
        -TaskName "BiliveRecorder" `
        -PythonExe (Join-Path $ProjectDir ".venv-recorder\Scripts\pythonw.exe") `
        -ModuleName "src.server.recorder_server" `
        -Port 2233 `
        -Description "Local bilive blrec recorder on 127.0.0.1:2233."
    $registeredTasks += "BiliveRecorder"
}
if (-not $NoDashboard) {
    Register-BiliveLogonTask `
        -TaskName "BiliveDashboard" `
        -PythonExe (Join-Path $ProjectDir ".venv-win\Scripts\pythonw.exe") `
        -ModuleName "src.server.dashboard_server" `
        -Port 2234 `
        -Description "Local bilive dashboard on 127.0.0.1:2234."
    $registeredTasks += "BiliveDashboard"
}

Get-ScheduledTask -TaskName $registeredTasks | Select-Object TaskName, State
