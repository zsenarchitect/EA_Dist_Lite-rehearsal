# Helper function to get EnneadTab dump folder. The office L: drive is retired.
# Never last-resort to L:. Writes go to the local ecosystem Dump folder.
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

$sharedFolder = Get-EnneadTabDumpFolder
if (-not (Test-Path $sharedFolder)) {
    New-Item -ItemType Directory -Path $sharedFolder -Force | Out-Null
}
$user = $env:USERNAME
$pc = $env:COMPUTERNAME
$file = "PINCONNECTION_${user}_${pc}.DuckPin"
$date = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$content = "Last check-in: $date"

try {
    Set-Content -Path (Join-Path $sharedFolder $file) -Value $content -ErrorAction Stop
}
catch {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show("Cannot write the EnneadTab check-in file. Shared network folder is not available.", "Network Connection Error", "OK", "Error")
} 