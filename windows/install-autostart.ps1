<#
.SYNOPSIS
    Register a per-user scheduled task that starts the docvault server at logon.

.DESCRIPTION
    Creates a Task Scheduler entry under the current user (no admin required)
    that runs windows\docvault-server.bat at every interactive logon. The bat
    file uses pythonw.exe under the project's .venv, so no console window
    appears.

    Idempotent -- re-registers (Force) on every run, so flag/path changes in
    the bat file are picked up on the next reboot.

    The task name is "Docvault Server (user logon)". Run uninstall-autostart.ps1
    (or windows\uninstall.ps1) to remove.
#>

$ErrorActionPreference = 'Stop'

$here       = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $here
$serverBat  = Join-Path $here 'docvault-server.bat'
$taskName   = 'Docvault Server (user logon)'

if (-not (Test-Path -LiteralPath $serverBat)) {
    throw "missing $serverBat -- run setup.ps1 first"
}

# Use cmd /c to invoke the .bat without a flashing window. The bat itself
# uses 'start "" /B pythonw.exe' so no terminal is visible after launch.
# A 5-second delay after logon avoids racing the brief window where pip /
# python can be slow on a cold disk.
$action = New-ScheduledTaskAction `
    -Execute 'cmd.exe' `
    -Argument "/c `"$serverBat`"" `
    -WorkingDirectory $projectRoot

$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$trigger.Delay = 'PT5S'   # ISO-8601 duration; 5-second delay after logon

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew

# Hidden = the cmd /c launcher exits in <1s; we hide its console window.
$settings.Hidden = $true

$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "Starts the docvault local server in the background at user logon. Managed by docvault\windows\install-autostart.ps1."

Register-ScheduledTask -TaskName $taskName -InputObject $task -Force | Out-Null

Write-Host "registered scheduled task: $taskName"
Write-Host "  action: cmd /c `"$serverBat`""
Write-Host "  trigger: at logon ($env:USERDOMAIN\$env:USERNAME), 5s delay"
Write-Host ""
Write-Host "Manage via Task Scheduler (taskschd.msc) or:"
Write-Host "  Get-ScheduledTask -TaskName '$taskName'"
Write-Host "  Start-ScheduledTask  -TaskName '$taskName'    # run now"
Write-Host "  Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false"
