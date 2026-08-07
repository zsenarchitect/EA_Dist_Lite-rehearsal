#Requires -Version 3.0
<#
.SYNOPSIS
    Fixes pyRevit.addin files by replacing Administrator paths with current user paths.

.DESCRIPTION
    This script automatically requests admin elevation and fixes pyRevit.addin files
    across all Revit versions in ProgramData by replacing Administrator AppData paths
    with the current logged-in user's AppData path.

    Writes UTF-8 without BOM (preserves most .addin authoring). Files with a BOM in
    the original will lose it on rewrite.

.PARAMETER OriginalUser
    The interactive (non-elevated) username. Set automatically when the script
    self-elevates via UAC. Do not pass this manually unless debugging.

.EXAMPLE
    .\FixPyRevitAdminPath.ps1
    Double-click the script. UAC prompt will appear; supply IT admin credentials
    if prompted (over-the-shoulder elevation is supported — the original interactive
    user is detected and preserved across elevation).
#>

param(
    [string]$OriginalUser
)

# Set error action preference
$ErrorActionPreference = "Continue"

# Resolve the INTERACTIVE user (the user whose pyRevit paths need fixing),
# NOT $env:USERNAME — which, under over-the-shoulder UAC elevation, becomes the
# admin account that supplied credentials. If $OriginalUser wasn't passed in
# (first invocation, before elevation), fall back to $env:USERNAME.
if (-not $OriginalUser -or $OriginalUser.Trim() -eq "") {
    $OriginalUser = $env:USERNAME
}
$currentUsername = $OriginalUser

# Check if the INTERACTIVE user is Administrator — only then is there nothing to fix.
if ($currentUsername -eq "Administrator") {
    Write-Host "`nWARNING: Interactive user is 'Administrator'. No replacement needed." -ForegroundColor Yellow
    Write-Host "Press any key to exit..."
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 0
}

# Function to check if running as administrator
function Test-Administrator {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentUser)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Function to elevate script if not running as admin
function Request-AdminElevation {
    if (-not (Test-Administrator)) {
        Write-Host "`nThis script requires administrator privileges to modify files in ProgramData." -ForegroundColor Yellow
        Write-Host "Requesting elevation..." -ForegroundColor Yellow
        
        try {
            # Re-launch script with admin privileges.
            # CRITICAL: pass the current $currentUsername as -OriginalUser so that
            # over-the-shoulder UAC elevation (IT typing admin creds on a non-admin
            # user's machine) doesn't lose the real interactive user's identity.
            $scriptPath = if ($PSCommandPath) { $PSCommandPath } else { $MyInvocation.MyCommand.Path }
            $escapedUser = $currentUsername -replace '"', '\"'
            $processInfo = New-Object System.Diagnostics.ProcessStartInfo
            $processInfo.FileName = "powershell.exe"
            $processInfo.Arguments = "-ExecutionPolicy Bypass -NoProfile -File `"$scriptPath`" -OriginalUser `"$escapedUser`""
            $processInfo.Verb = "runas"
            $processInfo.UseShellExecute = $true

            $process = [System.Diagnostics.Process]::Start($processInfo)
            exit 0
        }
        catch {
            Write-Host "`nERROR: Failed to elevate privileges. Please run this script as Administrator manually." -ForegroundColor Red
            Write-Host "Right-click the script and select 'Run as administrator'" -ForegroundColor Yellow
            Write-Host "`nPress any key to exit..."
            $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
            exit 1
        }
    }
}

# Request admin elevation if needed
Request-AdminElevation

# Verify we're now running as admin
if (-not (Test-Administrator)) {
    Write-Host "`nERROR: Still not running as administrator. Exiting." -ForegroundColor Red
    Write-Host "Press any key to exit..."
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 1
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  Fix PyRevit Admin Path Script" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Running as Administrator: Yes" -ForegroundColor Green
Write-Host "Current User: $currentUsername" -ForegroundColor Green
Write-Host ""

# Define paths
$addinsBasePath = "C:\ProgramData\Autodesk\Revit\Addins"
$targetFileName = "pyRevit.addin"  # Exact match, case-sensitive

# Check if Addins folder exists
if (-not (Test-Path $addinsBasePath)) {
    Write-Host "ERROR: Addins folder not found: $addinsBasePath" -ForegroundColor Red
    Write-Host "Press any key to exit..."
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 1
}

# Get all version folders
$versionFolders = Get-ChildItem -Path $addinsBasePath -Directory -ErrorAction SilentlyContinue | 
    Where-Object { $_.Name -match '^\d{4}$' } | 
    Sort-Object Name

if ($versionFolders.Count -eq 0) {
    Write-Host "No Revit version folders found in: $addinsBasePath" -ForegroundColor Yellow
    Write-Host "Press any key to exit..."
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 0
}

Write-Host "Found $($versionFolders.Count) Revit version folder(s)" -ForegroundColor Cyan
Write-Host ""

# Statistics
$filesFound = 0
$filesFixed = 0
$filesSkipped = 0
$filesError = 0
$processedFiles = @()

# Patterns for matching and replacement
# NOTE: PowerShell strings do NOT interpret "\\" as an escape — it is two literal
# backslashes. For regex we must feed a single-backslash source through
# [regex]::Escape(...) exactly once. Real pyRevit.addin XML contains single
# backslashes (e.g. C:\Users\Administrator\AppData\...), not doubled.
$adminPathLiteral  = "C:\Users\Administrator\AppData"
$adminPathRegex    = [regex]::Escape($adminPathLiteral)
$currentUserPath   = "C:\Users\$currentUsername\AppData"
$currentUserRegex  = [regex]::Escape($currentUserPath)

# Function to check if file is already fixed
function Test-FileAlreadyFixed {
    param([string]$fileContent)

    # Already fixed = contains current-user path AND no Administrator path remains
    if ($fileContent -match $currentUserRegex -and $fileContent -notmatch $adminPathRegex) {
        return $true
    }
    return $false
}

# Function to safely read file with retry
function Read-FileWithRetry {
    param(
        [string]$filePath,
        [int]$maxRetries = 3
    )
    
    for ($attempt = 1; $attempt -le $maxRetries; $attempt++) {
        try {
            # Try to read the file
            $content = Get-Content -Path $filePath -Raw -Encoding UTF8 -ErrorAction Stop
            return $content
        }
        catch {
            if ($attempt -lt $maxRetries) {
                $delay = [math]::Pow(2, $attempt - 1)  # Exponential backoff: 1s, 2s, 4s
                Write-Host "  File locked (attempt $attempt/$maxRetries), retrying in $delay seconds..." -ForegroundColor Yellow
                Start-Sleep -Seconds $delay
            }
            else {
                throw
            }
        }
    }
}

# Function to safely write file with retry
function Write-FileWithRetry {
    param(
        [string]$filePath,
        [string]$content,
        [int]$maxRetries = 3
    )
    
    for ($attempt = 1; $attempt -le $maxRetries; $attempt++) {
        try {
            # Remove read-only attribute if present
            if (Test-Path $filePath) {
                $fileItem = Get-Item $filePath
                if ($fileItem.IsReadOnly) {
                    Set-ItemProperty -Path $filePath -Name IsReadOnly -Value $false -ErrorAction SilentlyContinue
                }
            }
            
            # Write file with UTF-8 encoding (no BOM to match original)
            $utf8NoBom = New-Object System.Text.UTF8Encoding $false
            [System.IO.File]::WriteAllText($filePath, $content, $utf8NoBom)
            return $true
        }
        catch {
            if ($attempt -lt $maxRetries) {
                $delay = [math]::Pow(2, $attempt - 1)  # Exponential backoff
                Write-Host "  File locked (attempt $attempt/$maxRetries), retrying in $delay seconds..." -ForegroundColor Yellow
                Start-Sleep -Seconds $delay
            }
            else {
                throw
            }
        }
    }
}

# Process each version folder
foreach ($versionFolder in $versionFolders) {
    $versionPath = $versionFolder.FullName
    $targetFile = Join-Path $versionPath $targetFileName
    
    Write-Host "Checking: $($versionFolder.Name)" -ForegroundColor Cyan
    
    # Check if pyRevit.addin exists (exact match, case-sensitive)
    if (-not (Test-Path $targetFile)) {
        Write-Host "  -> pyRevit.addin not found, skipping" -ForegroundColor Gray
        continue
    }
    
    $filesFound++
    Write-Host "  -> Found pyRevit.addin" -ForegroundColor Green
    
    try {
        # Read file content with retry
        $fileContent = Read-FileWithRetry -FilePath $targetFile
        
        # Check if file is already fixed
        if (Test-FileAlreadyFixed -fileContent $fileContent) {
            Write-Host "  -> Already using correct path ($currentUsername), skipping" -ForegroundColor Yellow
            $filesSkipped++
            $processedFiles += [PSCustomObject]@{
                Version = $versionFolder.Name
                File = $targetFile
                Status = "Skipped (already fixed)"
            }
            continue
        }
        
        # Check if file contains Administrator path (case-insensitive)
        if ($fileContent -notmatch $adminPathRegex) {
            Write-Host "  -> No Administrator path found, skipping" -ForegroundColor Yellow
            $filesSkipped++
            $processedFiles += [PSCustomObject]@{
                Version = $versionFolder.Name
                File = $targetFile
                Status = "Skipped (no Administrator path)"
            }
            continue
        }

        # Perform replacement (case-insensitive via -replace, all occurrences)
        $originalContent = $fileContent
        $newContent = $fileContent -replace $adminPathRegex, $currentUserPath
        
        # Verify replacement occurred
        if ($newContent -eq $originalContent) {
            Write-Host "  -> Replacement pattern not matched, skipping" -ForegroundColor Yellow
            $filesSkipped++
            $processedFiles += [PSCustomObject]@{
                Version = $versionFolder.Name
                File = $targetFile
                Status = "Skipped (pattern not matched)"
            }
            continue
        }
        
        # Write file with retry
        Write-FileWithRetry -FilePath $targetFile -Content $newContent
        
        Write-Host "  -> Fixed: Replaced Administrator path with $currentUsername path" -ForegroundColor Green
        $filesFixed++
        $processedFiles += [PSCustomObject]@{
            Version = $versionFolder.Name
            File = $targetFile
            Status = "Fixed"
        }
    }
    catch {
        Write-Host "  -> ERROR: $($_.Exception.Message)" -ForegroundColor Red
        $filesError++
        $processedFiles += [PSCustomObject]@{
            Version = $versionFolder.Name
            File = $targetFile
            Status = "Error: $($_.Exception.Message)"
        }
    }
    
    Write-Host ""
}

# Summary
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Summary" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Files found:        $filesFound" -ForegroundColor White
Write-Host "Files fixed:        $filesFixed" -ForegroundColor Green
Write-Host "Files skipped:      $filesSkipped" -ForegroundColor Yellow
Write-Host "Files with errors:  $filesError" -ForegroundColor $(if ($filesError -gt 0) { "Red" } else { "White" })
Write-Host ""

if ($processedFiles.Count -gt 0) {
    Write-Host "Detailed Results:" -ForegroundColor Cyan
    $processedFiles | Format-Table -AutoSize
}

# Exit-code decision:
#   - Real error during rewrite -> exit 2, red ERROR (investigate).
#   - At least one file fixed this run -> exit 0, green (action taken).
#   - No fixes needed because every found file was already on the correct path
#     -> exit 0, green (healthy no-op; re-run on an already-correct machine).
#   - No files matched the pyRevit.addin target at all -> exit 2, red WARNING
#     (likely broken install / wrong paths; loud-fail per
#     feedback_files_skipped_is_not_success.md).
$filesAlreadyFixed = ($processedFiles | Where-Object { $_.Status -eq "Skipped (already fixed)" }).Count

$exitCode = 0
if ($filesError -gt 0) {
    Write-Host ""
    Write-Host "ERROR: $filesError file(s) failed to rewrite. See Detailed Results above." -ForegroundColor Red
    $exitCode = 2
} elseif ($filesFixed -gt 0) {
    Write-Host ""
    Write-Host "Fixed $filesFixed file(s)." -ForegroundColor Green
    $exitCode = 0
} elseif ($filesAlreadyFixed -gt 0) {
    Write-Host ""
    Write-Host "No action needed - all $filesAlreadyFixed pyRevit.addin file(s) already on the correct path." -ForegroundColor Green
    $exitCode = 0
} elseif ($filesFound -eq 0) {
    Write-Host ""
    Write-Host "WARNING: no files matched pattern - verify pyRevit install." -ForegroundColor Red
    Write-Host "Expected to find pyRevit.addin under $addinsBasePath\<version>\." -ForegroundColor Yellow
    Write-Host "Likely causes:" -ForegroundColor Yellow
    Write-Host "  - pyRevit not installed for any Revit version on this machine" -ForegroundColor Yellow
    Write-Host "  - ProgramData Addins folder missing expected layout" -ForegroundColor Yellow
    Write-Host "  - Filename case or spelling drift in a future pyRevit release" -ForegroundColor Yellow
    $exitCode = 2
} else {
    # Fallback: files were found but all skipped for non-"already fixed" reasons
    # (e.g. "pattern not matched" on non-Administrator paths). Treat as warning.
    Write-Host ""
    Write-Host "WARNING: Found $filesFound pyRevit.addin file(s) but fixed 0." -ForegroundColor Red
    Write-Host "Check the Detailed Results above for the per-file reason." -ForegroundColor Yellow
    $exitCode = 2
}

Write-Host ""
Write-Host "Script completed (exit=$exitCode). Press any key to exit..." -ForegroundColor Cyan
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
exit $exitCode

