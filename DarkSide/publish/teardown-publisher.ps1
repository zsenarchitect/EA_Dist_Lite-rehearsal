<#
.SYNOPSIS
    Un-enroll THIS machine as the EnneadTab publisher, and prove it is no longer one.

.DESCRIPTION
    The inverse of setup-publisher.ps1. Removes the enrollment marker and, unless
    -KeepTask is given, unregisters the scheduled task.

    It then VERIFIES the machine no longer reads as the publisher, and checks that
    no leftover persistence remains. That second check matters: there used to be a
    second registrar (Apps/lib/DumpScripts/_register_shcedule_publisher.py) that
    also wrote a Startup-folder .bat, which the old unregister script never
    removed. A teardown that only deletes what it knows about is how a "retired"
    publisher keeps publishing.

.PARAMETER KeepTask
    Leave the Windows scheduled task registered (un-enroll only). The task will
    still fire but the publisher will decline to pull or publish.

.EXAMPLE
    .\teardown-publisher.ps1
#>
[CmdletBinding()]
param(
    [switch]$KeepTask
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir '..\..')
$TaskName = 'EnneadTab_SchedulePublisher'

function Get-PythonExe {
    $venv = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (Test-Path $venv) { return $venv }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw "No python found. Expected $venv or python on PATH."
}

$Python = Get-PythonExe
Write-Host "=== EnneadTab publisher teardown ===" -ForegroundColor Cyan
Write-Host "Machine : $env:COMPUTERNAME"
Write-Host ""
Write-Host "Before:" -ForegroundColor Cyan
& $Python (Join-Path $ScriptDir 'publisher_enrollment.py')
Write-Host ""

$removed = & $Python -c "import sys; sys.path.insert(0, r'$ScriptDir'); import publisher_enrollment as pe; print('REMOVED' if pe.disable() else 'NO_MARKER')"
Write-Host "Enrollment marker: $removed"

if (-not $KeepTask) {
    Write-Host ""
    Write-Host "Unregistering scheduled task '$TaskName'..." -ForegroundColor Cyan
    # Not the old _unregister bat: it ends in `pause`, so it cannot be driven
    # non-interactively (by CI, or by a remote handoff).
    try { schtasks /delete /tn $TaskName /f 2>&1 | Out-Null } catch { }
    try { schtasks /delete /tn 'EnneadTab Publisher' /f 2>&1 | Out-Null } catch { }
}

Write-Host ""
Write-Host "Verifying this machine is no longer the publisher:" -ForegroundColor Cyan
$failures = @()

$enrolled = & $Python -c "import sys; sys.path.insert(0, r'$ScriptDir'); import publisher_enrollment as pe; print('ENROLLED' if pe.is_enrolled() else 'NOT_ENROLLED')"
if ($enrolled -match '^ENROLLED') { $failures += "still reads as enrolled" }
else { Write-Host "  OK - not enrolled" -ForegroundColor Green }

if (-not $KeepTask) {
    $taskLeft = schtasks /query /tn $TaskName 2>$null
    if ($LASTEXITCODE -eq 0) { $failures += "scheduled task '$TaskName' still registered" }
    else { Write-Host "  OK - scheduled task not registered" -ForegroundColor Green }
}

# The leftover the old unregister path never cleaned.
$startupBat = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup\EnneadTab_SchedulePublisher.bat'
if (Test-Path $startupBat) {
    $failures += "Startup-folder persistence still present: $startupBat"
} else {
    Write-Host "  OK - no Startup-folder persistence" -ForegroundColor Green
}

Write-Host ""
if ($failures.Count -gt 0) {
    Write-Host "TEARDOWN INCOMPLETE - this machine may still publish:" -ForegroundColor Red
    foreach ($f in $failures) { Write-Host "  * $f" -ForegroundColor Red }
    exit 1
}

Write-Host "Teardown complete. This machine will not pull or publish." -ForegroundColor Green
exit 0
