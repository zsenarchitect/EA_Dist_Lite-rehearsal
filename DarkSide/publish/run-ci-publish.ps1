#requires -Version 5.1
<#
.SYNOPSIS
    CI entry for the EnneadTab publisher. Rehearsal by default; production
    only under an explicit -Production switch.

.DESCRIPTION
    This is the #3269 dispatch door, and which distribution it reaches is
    decided HERE, by the caller, in one visible token.

    Standing constraints encoded here, not in a comment:
      * WITHOUT -Production: ENNEADTAB_PUBLISH_REHEARSAL_TARGETS must be set.
        Unset would fall through to Ennead-Architects-LLP/EA_Dist. Refused.
      * WITH -Production: the same variable must be ABSENT, and the tree must
        then AFFIRMATIVELY prove it targets production (publish_guard.py
        --assert-production: every EA_Dist* sibling on its production remote,
        nothing extra). The switch inverts the check; it never skips it. A
        skipped check is how the false-success class starts -- run 31633491120
        failed because this script could refuse a missing rehearsal override
        and had no way at all to affirm a production one.
      * The publish tree is ENNEADTAB_PUBLISHER_CLONE — a dedicated clean
        clone with sibling EA_Dist / EA_Dist_Lite folders. Never
        GITHUB_WORKSPACE (no siblings) and never a developer working
        directory (#3737 dirty-tree abort + half-finished edits). One tree
        serves exactly one destination: the rehearsal override changes what
        the guard EXPECTS, never where a force-push lands.
      * This MACHINE must be enrolled (publisher_enrollment.py). The clone
        path may differ from enrollment.repo_path.

    The script that GITHUB_WORKSPACE just checked out is the one that runs.
    It then resets the dedicated clone to -Sha (fetched from GITHUB_WORKSPACE
    when present, else origin) and publishes FROM that clone so sibling
    discovery hits that tree's dist repos.

    tools/check_publisher_ci_safety.py asserts the gate on the callers:
    publish-production.yml must pass -Production, publish-rehearsal.yml must
    never pass it.

.PARAMETER Sha
    Commit to publish from. In Actions this is github.sha. Locally, omit
    to use origin/main after fetch.

.PARAMETER Production
    Publish to the REAL distribution repos, and therefore to ~50 end-user
    machines. Only publish-production.yml may pass this.
#>
[CmdletBinding()]
param(
    [string]$Sha = "",
    [switch]$Production
)

$ErrorActionPreference = 'Stop'

function Fail([string]$Message) {
    Write-Host "CI PUBLISH REFUSED: $Message" -ForegroundColor Red
    exit 1
}

$productionRemotes = @(
    "github.com/Ennead-Architects-LLP/EA_Dist",
    "github.com/EnneadTab-EcoSystem/EA_Dist_Lite"
)

$rehearsal = [Environment]::GetEnvironmentVariable("ENNEADTAB_PUBLISH_REHEARSAL_TARGETS")

if ($Production) {
    # The inverse of the rehearsal check, not the absence of one. The positive
    # half -- that the tree really is aimed at production -- cannot be answered
    # from an environment variable, so it is asserted against the remotes on
    # disk after the clone is reset (publish_guard --assert-production below).
    if (-not [string]::IsNullOrWhiteSpace($rehearsal)) {
        Fail "-Production was passed with ENNEADTAB_PUBLISH_REHEARSAL_TARGETS set. That would ship to the rehearsal forks while reporting a production publish; the fleet would go stale behind a green check."
    }
} else {
    if ([string]::IsNullOrWhiteSpace($rehearsal)) {
        Fail "ENNEADTAB_PUBLISH_REHEARSAL_TARGETS is unset. CI must not fall through to production remotes. A real production publish requires -Production."
    }

    foreach ($remote in $productionRemotes) {
        # Match the production remote, but not a -rehearsal (or other) suffix.
        $pattern = [regex]::Escape($remote) + '(?:\.git)?(?![\w-])'
        if ([regex]::IsMatch($rehearsal, $pattern)) {
            Fail "Rehearsal targets include production remote $remote"
        }
    }
}

$clone = [Environment]::GetEnvironmentVariable("ENNEADTAB_PUBLISHER_CLONE")
if ([string]::IsNullOrWhiteSpace($clone)) {
    $cloneFile = Join-Path $env:USERPROFILE ".enneadtab\publisher-ci-clone"
    if (Test-Path -LiteralPath $cloneFile) {
        $clone = (Get-Content -LiteralPath $cloneFile -TotalCount 1).Trim()
    }
}
if ([string]::IsNullOrWhiteSpace($clone)) {
    Fail "ENNEADTAB_PUBLISHER_CLONE is unset. Set the Actions variable or write the dedicated rehearsal OS clone path to ~/.enneadtab/publisher-ci-clone."
}
if (-not (Test-Path -LiteralPath $clone)) {
    Fail "ENNEADTAB_PUBLISHER_CLONE does not exist: $clone"
}
$workspace = [Environment]::GetEnvironmentVariable("GITHUB_WORKSPACE")
if (-not [string]::IsNullOrWhiteSpace($workspace)) {
    $cloneFull = [IO.Path]::GetFullPath($clone)
    $workspaceFull = [IO.Path]::GetFullPath($workspace)
    if ($cloneFull -eq $workspaceFull) {
        Fail "ENNEADTAB_PUBLISHER_CLONE is GITHUB_WORKSPACE. Publish from a dedicated clone that has sibling dist repos (#3737)."
    }
}

$python = Join-Path $clone ".venv\Scripts\python.exe"
$publishPy = Join-Path $clone "DarkSide\publish\________publish.py"
$guardPy = Join-Path $clone "DarkSide\publish\publish_guard.py"
$enrollPy = Join-Path $clone "DarkSide\publish\publisher_enrollment.py"
foreach ($path in @($python, $publishPy, $guardPy, $enrollPy)) {
    if (-not (Test-Path -LiteralPath $path)) {
        Fail "Missing $path"
    }
}

$mode = if ($Production) { "PRODUCTION" } else { "rehearsal" }
Write-Host "=== CI $mode publish ===" -ForegroundColor $(if ($Production) { "Yellow" } else { "Cyan" })
Write-Host "Machine : $env:COMPUTERNAME"
Write-Host "Clone   : $clone"
Write-Host "Python  : $python"
Write-Host "Sha     : $(if ($Sha) { $Sha } else { '(origin/main after fetch)' })"
Write-Host ""

Push-Location $clone
try {
    Write-Host "Enrollment:" -ForegroundColor Cyan
    $enrollLines = & $python $enrollPy 2>&1
    $enrollLines | ForEach-Object { Write-Host $_ }
    $enrollText = ($enrollLines | Out-String)
    if ($enrollText -notmatch 'enrolled: True') {
        Fail "This machine is not enrolled as publisher. Run setup-publisher.ps1 (without -RegisterTask)."
    }
    Write-Host ""

    Write-Host "Reset dedicated clone:" -ForegroundColor Cyan
    $inside = git rev-parse --is-inside-work-tree
    if ($LASTEXITCODE -ne 0 -or "$inside".Trim() -ne "true") {
        Fail "$clone is not a git work tree"
    }

    $source = [Environment]::GetEnvironmentVariable("GITHUB_WORKSPACE")
    if (-not [string]::IsNullOrWhiteSpace($source) -and (Test-Path -LiteralPath $source)) {
        if ([string]::IsNullOrWhiteSpace($Sha)) {
            Fail "Sha is required when GITHUB_WORKSPACE is set (pass github.sha)."
        }
        Write-Host "  fetch $Sha from GITHUB_WORKSPACE"
        git fetch -- "$source" $Sha
        if ($LASTEXITCODE -ne 0) {
            Fail "git fetch from GITHUB_WORKSPACE failed (exit $LASTEXITCODE)"
        }
        git reset --hard $Sha
        if ($LASTEXITCODE -ne 0) {
            Fail "git reset --hard $Sha failed (exit $LASTEXITCODE)"
        }
    } else {
        git fetch origin
        if ($LASTEXITCODE -ne 0) {
            Fail "git fetch origin failed (exit $LASTEXITCODE)"
        }
        if ([string]::IsNullOrWhiteSpace($Sha)) {
            $Sha = "origin/main"
        }
        git reset --hard $Sha
        if ($LASTEXITCODE -ne 0) {
            Fail "git reset --hard $Sha failed (exit $LASTEXITCODE)"
        }
    }

    # Untracked non-ignored files trip the dirty-tree abort. Ignored paths
    # (.venv, logs) stay. -fd does not remove ignored files.
    git clean -fd
    $porcelain = git status --porcelain
    if ($porcelain) {
        Fail "Dedicated clone is still dirty after reset:`n$porcelain"
    }
    Write-Host "  HEAD $(git rev-parse --short HEAD) clean"
    Write-Host ""

    # Capture the RESOLVED commit ONCE, right after the reset that is meant to land
    # on it, and export it for ________publish.py to read. A publish run can take up
    # to 90 minutes (timeout-minutes in publish-production.yml); if the stamp writer
    # instead re-derives "the commit we published" via a live `git rev-parse HEAD` at
    # write time, any later git operation on this same clone during that window
    # (however unlikely) would silently drift the stamp away from the SHA this run
    # actually dispatched on. Exporting it now removes that window (senzhang-todo #4417).
    $resolvedSha = (git rev-parse HEAD | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($resolvedSha)) {
        Fail "Could not resolve HEAD after reset to capture ENNEADTAB_PUBLISH_SHA"
    }
    $env:ENNEADTAB_PUBLISH_SHA = $resolvedSha

    # Sync sibling dist repos: if a clean dist repo is behind origin/main, fast-forward it
    # so publish builds on top of any remote commits rather than failing on STALE_CLONE.
    # Relax $ErrorActionPreference around native git commands on PS 5.1 to prevent NativeCommandError on stderr.
    Write-Host "Sync sibling dist repos:" -ForegroundColor Cyan
    $parentDir = Split-Path -Parent $clone
    $prevSyncEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        Get-ChildItem -LiteralPath $parentDir -Directory | Where-Object { $_.Name -like 'EA_Dist*' } | ForEach-Object {
            $distPath = $_.FullName
            Write-Host "  Checking $distPath ..."
            Push-Location $distPath
            try {
                $isGit = (git rev-parse --is-inside-work-tree 2>&1 | Out-String).Trim()
                if ($LASTEXITCODE -eq 0 -and $isGit -eq "true") {
                    $status = (git status --porcelain 2>&1 | Out-String).Trim()
                    if (-not $status) {
                        git -c gc.auto=0 fetch origin main 2>&1 | Out-Null
                        if ($LASTEXITCODE -eq 0) {
                            $diffCount = (git rev-list --left-right --count origin/main...HEAD 2>&1 | Out-String).Trim()
                            if ($LASTEXITCODE -eq 0 -and $diffCount -match '^\s*(\d+)\s+(\d+)\s*$') {
                                $behind = [int]$matches[1]
                                $ahead = [int]$matches[2]
                                if ($behind -gt 0 -and $ahead -eq 0) {
                                    Write-Host "    Fast-forwarding $behind commit(s) from origin/main..." -ForegroundColor Yellow
                                    git merge --ff-only origin/main 2>&1 | Out-Null
                                    if ($LASTEXITCODE -ne 0) {
                                        Write-Host "    Warning: git merge --ff-only failed (exit $LASTEXITCODE)" -ForegroundColor Yellow
                                    } else {
                                        Write-Host "    Successfully fast-forwarded to $(git rev-parse --short HEAD)" -ForegroundColor Green
                                    }
                                } else {
                                    Write-Host "    Already up to date (behind=$behind, ahead=$ahead)"
                                }
                            }
                        }
                    } else {
                        Write-Host "    Skipping sync: working tree is dirty" -ForegroundColor Yellow
                    }
                }
            } finally {
                Pop-Location
            }
        }
    } finally {
        $ErrorActionPreference = $prevSyncEAP
    }
    Write-Host ""


    if ($Production) {
        # Runs against the RESET clone, so it reads the siblings this publish
        # will actually force-push -- not whatever the caller believed. The
        # rehearsal path deliberately does not run this: there, WRONG_REMOTE
        # inside --report is the equivalent assertion against the override map.
        # Capture stderr here too. The #4661 fix landed on the --report call below and
        # left this one bare, so the PRODUCTION-only assertion -- the one gating a
        # force-push to the fleet -- was still able to fail with nothing but an exit
        # code. Same EAP dance and the same reason: on Windows PowerShell 5.1,
        # $ErrorActionPreference = 'Stop' turns native stderr captured via 2>&1 into a
        # terminating NativeCommandError, so the script would die here and never reach
        # the Fail below. Do not "simplify" to a bare 2>&1 or a file redirect without
        # re-testing on 5.1 specifically.
        Write-Host "publish_guard --assert-production:" -ForegroundColor Yellow
        $prevAssertEAP = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $assertLines = & $python $guardPy --assert-production 2>&1
            $assertExit = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $prevAssertEAP
        }
        $assertLines | ForEach-Object { Write-Host $_ }
        if ($assertExit -ne 0) {
            $assertText = ($assertLines | Out-String).Trim()
            if ([string]::IsNullOrWhiteSpace($assertText)) {
                $assertText = "(the guard produced NO output on stdout or stderr -- see senzhang-todo #4661)"
            }
            Fail "publish_guard --assert-production exited $assertExit. -Production was passed but this tree does not provably target the production distribution.`n--- publish_guard output ---`n$assertText"
        }
        Write-Host ""
    }

    # Capture stderr with 2>&1 (the same pattern the enrollment call above uses).
    # Without it the guard's traceback goes nowhere: on 2026-08-21 run 32511676656
    # refused with NOTHING but "publish_guard exited 1" -- no banner, no problem
    # list, no traceback -- because the guard died inside
    # verify_publish_preconditions BEFORE its unconditional banner, and the only
    # explanation went to a stream this call discarded. The fleet silently went
    # stale (PR #192 never shipped) and the cause is still unknown, because the
    # evidence was thrown away. A refusal must never be output-free.
    # senzhang-todo #4661.
    # $ErrorActionPreference is 'Stop' (line 53). On Windows PowerShell 5.1 -- the host
    # the workflow actually uses -- that turns native-command stderr captured via 2>&1
    # into a TERMINATING NativeCommandError, so the script would die on this line and
    # never reach the Fail below. Verified on both hosts with a known-bad fixture:
    # relaxing EAP around the call passes on 5.1 AND pwsh 7, while redirecting stderr
    # to a temp file passes on pwsh 7 and THROWS on 5.1. Do not "simplify" this to a
    # bare 2>&1 or a file redirect without re-testing on 5.1 specifically.
    Write-Host "publish_guard --report:" -ForegroundColor Cyan
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $guardLines = & $python $guardPy --report 2>&1
        $guardExit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prevEAP
    }
    $guardLines | ForEach-Object { Write-Host $_ }
    if ($guardExit -ne 0) {
        $guardText = ($guardLines | Out-String).Trim()
        if ([string]::IsNullOrWhiteSpace($guardText)) {
            $guardText = "(the guard produced NO output on stdout or stderr -- it likely died before its banner; see senzhang-todo #4661)"
        }
        Fail "publish_guard exited $guardExit`n--- publish_guard output ---`n$guardText"
    }
    Write-Host ""

    Write-Host "________publish.py:" -ForegroundColor Cyan
    $env:PYTHONUNBUFFERED = "1"
    $env:ENNEADTAB_PUBLISH_CI = "1"
    if ([string]::IsNullOrWhiteSpace($env:ENNEADTAB_PUBLISH_MODE)) {
        $env:ENNEADTAB_PUBLISH_MODE = "ci"
    }
    & $python $publishPy
    $publishExit = $LASTEXITCODE
    Write-Host "PUBLISH_EXIT=$publishExit"
    exit $publishExit
} finally {
    Pop-Location
}
