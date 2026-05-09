<#
.SYNOPSIS
    Remove docvault context-menu verbs from HKCU.
#>

$ErrorActionPreference = 'Continue'

# See install-context-menu.ps1 for why we use reg.exe instead of Remove-Item:
# the literal '*' in HKCU\Software\Classes\* makes PowerShell's path engine
# attempt wildcard expansion, which hangs on a populated registry.

# File verbs
foreach ($k in 'Docvault','DocvaultAI','DocvaultInPlace') {
    $path = "HKCU\Software\Classes\*\shell\$k"
    & reg.exe delete $path /f 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "removed $path"
    } else {
        Write-Host "(not present) $path"
    }
}

# Folder verb
foreach ($k in 'DocvaultFolder') {
    $path = "HKCU\Software\Classes\Directory\shell\$k"
    & reg.exe delete $path /f 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "removed $path"
    } else {
        Write-Host "(not present) $path"
    }
}

Write-Host ""
Write-Host "Restart Explorer:  Stop-Process -Name explorer -Force; Start-Process explorer"
