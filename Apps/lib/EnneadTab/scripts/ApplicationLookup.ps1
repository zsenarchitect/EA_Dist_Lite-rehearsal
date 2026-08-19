# Requires -Version 3.0

# NOTE: This script is intended to be run as the current user only. It does not attempt to elevate privileges or impersonate another user.

<#
    Script:    ApplicationLookup.ps1
    Purpose:   Collect installed application versions for Revit, Rhino and Enscape,
               then dump them to the local EnneadTab Dump folder in a file named
               "APPVERSIONLOOKUP_[PC NAME].json".
               - No elevation required (read-only registry access).
               - Show progress for all users.

    Output example (JSON):
    {
        "PC"     : "DESKTOP-ABC123",
        "User"   : "jdoe",
        "Revit"  : [ "2024", "2023" ],
        "Rhino"  : [ "8", "7" ],
        "Enscape": [ "3.5.2" ]
    }
#>

# ------------------------------------------------------------
# Helper – Show progress for all users
function Write-Log {
    param(
        [Parameter(Mandatory)][string]$Message
    )
    Write-Host $Message
}

# ------------------------------------------------------------
# Helper – local dump folder. The office L: drive is retired; never last-resort to L:.
function Get-EnneadTabDumpFolder {
    $ecoSys = Join-Path $env:USERPROFILE "Documents\EnneadTab Ecosystem"
    $localDump = Join-Path $ecoSys "Dump"

    if ($env:EA_SHARED_ROOT -and $env:EA_SHARED_ROOT.Trim()) {
        $root = $env:EA_SHARED_ROOT.Trim()
        if ($root.ToUpper() -eq "OFFLINE" -or $root -match '^[Ll]:') {
            return $localDump
        }
        return (Join-Path $root "05_EnneadTab-DB\Shared Data Dump")
    }

    $candidates = @(
        (Join-Path $ecoSys "shared_root.json"),
        (Join-Path $ecoSys "EA_Dist\Apps\lib\EnneadTab\shared_root.json")
    )
    foreach ($candidate in $candidates) {
        if (-not (Test-Path $candidate)) { continue }
        try {
            $config = Get-Content $candidate -Raw | ConvertFrom-Json
            if ($config.offline -eq $true) { return $localDump }
            if ($config.db_folder -and $config.db_folder -notmatch '^[Ll]:') {
                return (Join-Path $config.db_folder "Shared Data Dump")
            }
            if ($config.shared_root -and $config.shared_root -notmatch '^[Ll]:') {
                return (Join-Path $config.shared_root "05_EnneadTab-DB\Shared Data Dump")
            }
        } catch {
            continue
        }
    }

    return $localDump
}

# ------------------------------------------------------------
# Helper – Fetch installed application entries from registry
function Get-InstalledApps {
    param(
        [Parameter(Mandatory)][string]$NamePattern    # regex to match DisplayName
    )

    $uninstallRoots = @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'
    )

    $allMatches = @()
    foreach ($root in $uninstallRoots) {
        $found = 0
        $items = Get-ChildItem -Path $root -ErrorAction SilentlyContinue
        foreach ($item in $items) {
            $props = Get-ItemProperty -Path $item.PSPath -ErrorAction SilentlyContinue
            if ($null -ne $props.DisplayName -and ($props.DisplayName -match $NamePattern)) {
                $allMatches += [PSCustomObject]@{
                    DisplayName    = $props.DisplayName
                    DisplayVersion = $props.DisplayVersion
                }
                $found++
            }
        }
        Write-Log "[DEBUG] $found matches in $root"
    }
    return $allMatches
}

# ------------------------------------------------------------
# Helper – Extract a clean version string
function Extract-Version {
    param(
        [Parameter(Mandatory)][string]$DisplayName,
        [string]$DisplayVersion
    )

    # 1) Prefer the detailed DisplayVersion if present (e.g., 23.1.60.36)
    if (-not [string]::IsNullOrWhiteSpace($DisplayVersion)) {
        return $DisplayVersion.Trim()
    }

    # 2) Fallbacks when DisplayVersion absent --------------------------------

    # Revit – pick the year from DisplayName (e.g., 2024)
    if ($DisplayName -match '(?<yr>20\d{2})') {
        return $Matches['yr']
    }

    # Rhino – pick major version (e.g., 8)
    if ($DisplayName -match '([Rr]hino(ceros)?\s*)(?<maj>\d+)') {
        return $Matches['maj']
    }

    # Last resort – return DisplayName
    return $DisplayName
}

# ------------------------------------------------------------
# Helper – Convert registry entries to list of {Name,Version}
function Convert-ToEntryList {
    param(
        [object[]]$Apps = @()
    )

    $list = @()
    foreach ($app in $Apps) {
        $version = if (-not [string]::IsNullOrWhiteSpace($app.DisplayVersion)) {
            $app.DisplayVersion.Trim()
        } else {
            Extract-Version $app.DisplayName ''
        }

        if (-not [string]::IsNullOrWhiteSpace($version)) {
            $list += [PSCustomObject]@{
                Name    = $app.DisplayName
                Version = $version
            }
        }
    }

    # Sort alphabetically for readability
    return $list | Sort-Object -Property Name
}

# ------------------------------------------------------------
# Collect versions
Write-Log "Collecting application versions..."

# Collect per-app entry lists ------------------------------------------------

# Revit: match any app with 'Revit' in the name (main app and add-ins)
$revitRaw = Get-InstalledApps -NamePattern 'Revit'
Write-Log ("[DEBUG] Revit raw entries: " + ($revitRaw | ConvertTo-Json -Depth 3))
$revitDict = @{}
foreach ($entry in $revitRaw) {
    if ($entry.DisplayName -and $entry.DisplayVersion) {
        $revitDict[$entry.DisplayName] = $entry.DisplayVersion
    }
}

$rhinoRaw = Get-InstalledApps -NamePattern 'Rhino'
Write-Log ("[DEBUG] Rhino raw entries: " + ($rhinoRaw | ConvertTo-Json -Depth 3))
Write-Log "[DEBUG] Checking registry paths for Rhino..."
$uninstallRoots = @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall',
    'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'
)
foreach ($root in $uninstallRoots) {
    Write-Log "[DEBUG] Checking $root"
    $items = Get-ChildItem -Path $root -ErrorAction SilentlyContinue
    foreach ($item in $items) {
        $props = Get-ItemProperty -Path $item.PSPath -ErrorAction SilentlyContinue
        if ($null -ne $props.DisplayName) {
            Write-Log "[DEBUG] Found app: $($props.DisplayName)"
        }
    }
}
$rhinoDict = @{}
foreach ($entry in $rhinoRaw) {
    if ($entry.DisplayName -and $entry.DisplayVersion) {
        $rhinoDict[$entry.DisplayName] = $entry.DisplayVersion
    }
}

$enscapeRaw = Get-InstalledApps -NamePattern '^Enscape'
Write-Log ("[DEBUG] Enscape raw entries: " + ($enscapeRaw | ConvertTo-Json -Depth 3))
$enscapeDict = @{}
foreach ($entry in $enscapeRaw) {
    if ($entry.DisplayName -and $entry.DisplayVersion) {
        $enscapeDict[$entry.DisplayName] = $entry.DisplayVersion
    }
}

# ------------------------------------------------------------
# Assemble output object (as dictionaries for each app type)
$result = [PSCustomObject]@{
    PC      = $env:COMPUTERNAME
    User    = $env:USERNAME
    Revit   = $revitDict
    Rhino   = $rhinoDict
    Enscape = $enscapeDict
}

# ------------------------------------------------------------
# Write to local dump (office L: share is retired)
$sharedDumpFolder = Get-EnneadTabDumpFolder
$targetFile = Join-Path -Path $sharedDumpFolder -ChildPath ("APPVERSIONLOOKUP_{0}.json" -f $env:COMPUTERNAME)

try {
    # Ensure directory exists
    if (-not (Test-Path -Path $sharedDumpFolder)) {
        New-Item -Path $sharedDumpFolder -ItemType Directory -Force | Out-Null
    }

    $result | ConvertTo-Json -Depth 3 | Out-File -FilePath $targetFile -Encoding UTF8
    Write-Log "Application version list written to $targetFile"
}
catch {
    Write-Log "Failed to write version list: $_"
}
