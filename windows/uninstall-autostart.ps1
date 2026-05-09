<#
.SYNOPSIS
    Remove the docvault logon scheduled task.
#>

$ErrorActionPreference = 'Continue'

$taskName = 'Docvault Server (user logon)'

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "removed scheduled task: $taskName"
} else {
    Write-Host "(not present) scheduled task: $taskName"
}
