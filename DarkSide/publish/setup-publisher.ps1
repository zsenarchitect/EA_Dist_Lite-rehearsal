<#
.SYNOPSIS
    Enroll THIS machine as the EnneadTab publisher. Portable; no hostname edits.

.DESCRIPTION
    Publisher eligibility used to be a hostname allowlist committed to the repo, in
    three places that disagreed with each other (one of them naming a machine that
    no longer exists, so it silently did nothing). Moving the publisher meant
    editing and committing source.

    This enrolls the machine you run it on. Teardown un-enrolls. Nothing about
    which machine publishes is committed to git.

    IMPORTANT: enrollment is REFUSED unless the machine actually proves it can
    publish. Creating a marker file is trivial; the useful part is that
    publish_guard has to pass first, so "setup succeeded" means "this box is
    genuinely publish-capable", not "a file was written". Use -Force to enroll
    anyway (for staged provisioning where you will fix prerequisites after).

.PARAMETER RegisterTask
    Also register the 10-minute Windows scheduled task. Omit if this machine will
    publish via CI or manual runs only.

.PARAMETER Force
    Enroll even if the pre-publish guard reports problems.

.EXAMPLE
    .\setup-publisher.ps1
    .\setup-publisher.ps1 -RegisterTask
#>
[CmdletBinding()]
param(
    [switch]$RegisterTask,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir '..\..')

function Get-PythonExe {
    $venv = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (Test-Path $venv) { return $venv }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw "No python found. Expected $venv or python on PATH."
}

$Python = Get-PythonExe
Write-Host "=== EnneadTab publisher setup ===" -ForegroundColor Cyan
Write-Host "Machine   : $env:COMPUTERNAME"
Write-Host "Repo      : $RepoRoot"
Write-Host "Python    : $Python"
Write-Host ""

Write-Host "Publisher Python deps (pyyaml / Pillow / reportlab / PyPDF2 / requests):" -ForegroundColor Cyan
& $Python -m pip install --disable-pip-version-check -q pyyaml Pillow reportlab pypdf2 requests
if ($LASTEXITCODE -ne 0) {
    Write-Host "pip install of publisher deps failed (exit $LASTEXITCODE)." -ForegroundColor Red
    if (-not $Force) { exit 1 }
}
Write-Host ""

Write-Host "Current status:" -ForegroundColor Cyan
& $Python (Join-Path $ScriptDir 'publisher_enrollment.py')
Write-Host ""

# The gate. Enrollment claims this machine can publish, so make it prove it.
Write-Host "Verifying this machine is publish-capable..." -ForegroundColor Cyan
& $Python (Join-Path $ScriptDir 'publish_guard.py') --report
$guardExit = $LASTEXITCODE
Write-Host ""

if ($guardExit -ne 0 -and -not $Force) {
    Write-Host "SETUP REFUSED." -ForegroundColor Red
    Write-Host "The pre-publish guard reported problems (exit $guardExit); see above."
    Write-Host "Enrolling now would produce a machine that believes it is the publisher"
    Write-Host "but cannot publish correctly. Fix the problems and re-run, or pass -Force"
    Write-Host "if you are provisioning in stages and will fix them before publishing."
    exit 1
}
if ($guardExit -ne 0) {
    Write-Host "WARNING: guard reported problems but -Force was given. Enrolling anyway." -ForegroundColor Yellow
    Write-Host "         This machine is NOT yet safe to publish from." -ForegroundColor Yellow
}

$stamp = (Get-Date).ToString('o')
$note = "enrolled by setup-publisher.ps1"
$enrollCode = @"
import sys, json
sys.path.insert(0, r'$ScriptDir')
import publisher_enrollment as pe
rec = pe.enable(r'$RepoRoot', note='''$note''', timestamp='''$stamp''')
print(json.dumps(rec, indent=2))
"@
& $Python -c $enrollCode
if ($LASTEXITCODE -ne 0) { Write-Host "Enrollment write FAILED." -ForegroundColor Red; exit 1 }

# Verify the write actually took, rather than trusting that it did.
Write-Host ""
Write-Host "Verifying enrollment:" -ForegroundColor Cyan
$verify = & $Python -c "import sys; sys.path.insert(0, r'$ScriptDir'); import publisher_enrollment as pe; print('ENROLLED' if pe.is_enrolled() else 'NOT_ENROLLED')"
if ($verify -notmatch 'ENROLLED') {
    Write-Host "FAILED: marker was written but this machine still does not read as enrolled." -ForegroundColor Red
    exit 1
}
Write-Host "  OK - this machine is enrolled as the publisher." -ForegroundColor Green

if ($RegisterTask) {
    Write-Host ""
    Write-Host "Registering the scheduled task..." -ForegroundColor Cyan
    & (Join-Path $ScriptDir '_register_schedule_publisher_task.bat')
}

Write-Host ""
Write-Host "Done. To un-enroll this machine: .\teardown-publisher.ps1" -ForegroundColor Cyan
exit 0
