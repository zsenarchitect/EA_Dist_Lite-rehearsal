<#
    diagnose-proDUCKtion.ps1

    For the report: "import proDUCKtion fails after installing EA_Dist, but the
    file is on my disk" -- affecting SOME users, not all.

    proDUCKtion.py lives in Apps\_revit\KingDuck.lib\. It is not imported by path;
    it is imported by NAME. That only works if pyRevit has put the KingDuck.lib
    folder on sys.path, which it does by scanning its extension search directories
    for *.lib folders.

    The diagnostic question is therefore NOT "does proDUCKtion.py exist" (it does).
    It is: WHICH EnneaDuck.extension is pyRevit actually loading, and does a
    KingDuck.lib sit next to THAT one?

    Two known ways they can disagree:

      A. The installer's find_main_repo() walks the whole user profile and returns
         ANY folder named 'EnneadTab-OS' -- a stale clone, a downloaded zip, a
         OneDrive copy -- in preference to EA_Dist. pyRevit is then pointed at
         that tree.

      B. pyRevit ALWAYS searches %APPDATA%\pyRevit\extensions and its thirdparty
         default dir, regardless of userextensions. An older install that COPIED
         EnneaDuck.extension there leaves a shadow copy with no KingDuck.lib
         sibling.

    In both cases the buttons load (the .extension is found) and every one of them
    dies on its first line at `import proDUCKtion` (the .lib is not).

    Read-only. Changes nothing.
#>

$ErrorActionPreference = 'Continue'

function Section($t) {
    Write-Host ''
    Write-Host ('=' * 74) -ForegroundColor DarkGray
    Write-Host "  $t" -ForegroundColor Cyan
    Write-Host ('=' * 74) -ForegroundColor DarkGray
}

Write-Host ''
Write-Host '  EnneadTab :: proDUCKtion import diagnostic' -ForegroundColor White
Write-Host "  machine=$env:COMPUTERNAME  user=$env:USERNAME" -ForegroundColor DarkGray

# ---------------------------------------------------------------- 1. config
Section '1. What pyRevit was told to search (userextensions)'

$configIni = Join-Path $env:APPDATA 'pyRevit\pyRevit_config.ini'
$registeredDirs = @()

if (-not (Test-Path -LiteralPath $configIni)) {
    Write-Host "  FAIL  pyRevit_config.ini not found at $configIni" -ForegroundColor Red
} else {
    $iniText = Get-Content -LiteralPath $configIni -Raw
    if ($iniText -match '(?ms)^\s*userextensions\s*=\s*(\[[^\]]*\])') {
        $listRaw = $matches[1]
        Write-Host "  raw value: $listRaw" -ForegroundColor Gray

        $entries = [regex]::Matches($listRaw, '"([^"]+)"') | ForEach-Object {
            $_.Groups[1].Value -replace '\\\\', '\'
        }
        foreach ($e in $entries) {
            $registeredDirs += $e
            $exists = Test-Path -LiteralPath $e
            Write-Host ("  registered -> {0}   [{1}]" -f $e, $(if ($exists) { 'exists' } else { 'MISSING' })) `
                -ForegroundColor $(if ($exists) { 'Green' } else { 'Red' })
        }
        if (-not $entries) {
            Write-Host '  FAIL  userextensions is empty -- no EnneadTab search path registered.' -ForegroundColor Red
        }

        # The encoding bug fixed 2026-07-13: raw single backslashes.
        $firstRaw = ''
        if ([regex]::Matches($listRaw, '"([^"]+)"').Count -gt 0) {
            $firstRaw = [regex]::Matches($listRaw, '"([^"]+)"')[0].Groups[1].Value
        }
        if ($firstRaw -match '(?<!\\)\\(?!\\)') {
            Write-Host '  WARN  stored with UNESCAPED backslashes (pre-2026-07-13 installer).' -ForegroundColor Yellow
            if ($firstRaw -match '[^\x00-\x7F]') {
                Write-Host '  FAIL  ...and the path is non-ASCII: pyRevit CANNOT parse this at all.' -ForegroundColor Red
            } else {
                Write-Host '        ASCII path, so pyRevit rescues it. Not your failure. Re-install to tidy.' -ForegroundColor DarkGray
            }
        }
    } else {
        Write-Host '  FAIL  no userextensions key in pyRevit_config.ini' -ForegroundColor Red
    }
}

# ------------------------------------------- 2. dirs pyRevit ALWAYS searches
Section '2. Directories pyRevit searches ANYWAY (not from userextensions)'

$defaultDirs = @(
    (Join-Path $env:APPDATA 'pyRevit\extensions'),
    (Join-Path $env:APPDATA 'pyRevit\Extensions')
) | Select-Object -Unique

foreach ($d in $defaultDirs) {
    if (Test-Path -LiteralPath $d) {
        Write-Host "  searched -> $d" -ForegroundColor Gray
        $shadow = Get-ChildItem -LiteralPath $d -Directory -ErrorAction SilentlyContinue |
                  Where-Object { $_.Name -like '*.extension' -or $_.Name -like '*.lib' }
        foreach ($s in $shadow) {
            Write-Host "     contains: $($s.Name)" -ForegroundColor Yellow
        }
        if ($shadow | Where-Object { $_.Name -eq 'EnneaDuck.extension' }) {
            Write-Host '  *** SHADOW COPY of EnneaDuck.extension lives in pyRevit''s own dir. ***' -ForegroundColor Red
            Write-Host '      pyRevit will load THIS one. If no KingDuck.lib sits beside it,' -ForegroundColor Red
            Write-Host '      every button fails at `import proDUCKtion`. This is cause (B).' -ForegroundColor Red
        }
        $registeredDirs += $d
    }
}

# ------------------------------------------------- 3. every copy on the disk
Section '3. Every EnneaDuck.extension / KingDuck.lib / proDUCKtion.py on this PC'

Write-Host '  scanning your user profile (this can take a minute)...' -ForegroundColor DarkGray

$exts = Get-ChildItem -LiteralPath $env:USERPROFILE -Directory -Recurse -Filter 'EnneaDuck.extension' -ErrorAction SilentlyContinue
$libs = Get-ChildItem -LiteralPath $env:USERPROFILE -Directory -Recurse -Filter 'KingDuck.lib'      -ErrorAction SilentlyContinue
$mods = Get-ChildItem -LiteralPath $env:USERPROFILE -File      -Recurse -Filter 'proDUCKtion.py'    -ErrorAction SilentlyContinue

Write-Host ''
Write-Host "  EnneaDuck.extension copies: $($exts.Count)" -ForegroundColor White
foreach ($e in $exts) { Write-Host "    $($e.FullName)" -ForegroundColor Gray }
Write-Host "  KingDuck.lib copies:        $($libs.Count)" -ForegroundColor White
foreach ($l in $libs) { Write-Host "    $($l.FullName)" -ForegroundColor Gray }
Write-Host "  proDUCKtion.py copies:      $($mods.Count)" -ForegroundColor White
foreach ($m in $mods) { Write-Host "    $($m.FullName)" -ForegroundColor Gray }

# stray EnneadTab-OS folders -- cause (A)
$strays = Get-ChildItem -LiteralPath $env:USERPROFILE -Directory -Recurse -Filter 'EnneadTab-OS' -ErrorAction SilentlyContinue
if ($strays) {
    Write-Host ''
    Write-Host "  *** $($strays.Count) folder(s) named 'EnneadTab-OS' found in your profile: ***" -ForegroundColor Red
    foreach ($s in $strays) { Write-Host "    $($s.FullName)" -ForegroundColor Red }
    Write-Host '      The installer''s find_main_repo() prefers ANY of these over EA_Dist,' -ForegroundColor Red
    Write-Host '      so pyRevit may be pointed at a stale tree. This is cause (A).' -ForegroundColor Red
}

# ------------------------------------------------------------- 4. the verdict
Section '4. VERDICT -- does a KingDuck.lib sit beside the extension pyRevit loads?'

$verdictFound = $false
foreach ($dir in ($registeredDirs | Select-Object -Unique)) {
    if (-not (Test-Path -LiteralPath $dir)) { continue }
    $ext = Join-Path $dir 'EnneaDuck.extension'
    if (-not (Test-Path -LiteralPath $ext)) { continue }

    $verdictFound = $true
    $lib  = Join-Path $dir 'KingDuck.lib'
    $prod = Join-Path $lib 'proDUCKtion.py'

    Write-Host ''
    Write-Host "  search dir : $dir" -ForegroundColor White
    Write-Host "    EnneaDuck.extension : FOUND (pyRevit loads buttons from here)" -ForegroundColor Green

    if (Test-Path -LiteralPath $prod) {
        Write-Host "    KingDuck.lib        : FOUND" -ForegroundColor Green
        Write-Host "    proDUCKtion.py      : FOUND" -ForegroundColor Green
        Write-Host '    -> This search dir is healthy.' -ForegroundColor Green
    } else {
        Write-Host "    KingDuck.lib        : $(if (Test-Path -LiteralPath $lib) { 'found but EMPTY of proDUCKtion.py' } else { 'MISSING' })" -ForegroundColor Red
        Write-Host '' -ForegroundColor Red
        Write-Host '    >>> THIS IS THE BUG. <<<' -ForegroundColor Red
        Write-Host '    pyRevit loads the buttons from this folder, but there is no' -ForegroundColor Red
        Write-Host '    KingDuck.lib next to it, so proDUCKtion is never put on sys.path.' -ForegroundColor Red
        Write-Host '    Every button dies on its first line at `import proDUCKtion`.' -ForegroundColor Red
        Write-Host '' -ForegroundColor Red
        Write-Host '    FIX: re-run Installation\EnneadTab_For_Revit_Installer.exe so pyRevit' -ForegroundColor Yellow
        Write-Host '         points at EA_Dist\Apps\_revit, and DELETE the stale copy above.' -ForegroundColor Yellow
    }
}

if (-not $verdictFound) {
    Write-Host '  No EnneaDuck.extension found in ANY directory pyRevit searches.' -ForegroundColor Red
    Write-Host '  Buttons would not appear at all. Re-run the Revit installer.' -ForegroundColor Yellow
}

Write-Host ''
Write-Host '  Send this whole output back to the DesignTech team.' -ForegroundColor Cyan
Write-Host ''
