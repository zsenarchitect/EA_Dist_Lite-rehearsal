<#
  sign-exeproducts.ps1 - Azure Trusted Signing for the EnneadTab runtime helper exes.
  =====================================================================================
  The 52 unsigned PyInstaller helpers in Apps/lib/ExeProducts (ExcelHandler.exe, Emailer.exe,
  ...) are refused by corporate endpoint security (AppLocker / Defender / EDR) because they are
  unsigned. This signs them with the SAME shared Azure Trusted Signing account every other
  EnneadTab app uses - via signtool + the Trusted Signing dlib, exactly the proven raw-PE path in
  EnneadTab-OneDriveResolver/native/pack-msix.ps1.

  DESIGNED TO RUN ON THE SELF-HOSTED `signing` RUNNER, where the SP secret lives (the dev machine
  that builds the exes has no credential - that is why they ship unsigned). See
  .github/workflows/sign-exeproducts.yml.

  UNSIGNED-BUT-GREEN: if AZURE_CLIENT_SECRET is absent (campaign over / wrong runner), the script
  prints a notice and exits 0 without signing - it never hard-fails a build for a missing cert.

  The 4 account values below are duplicated from EnneadTab-Certificate/sign/sign-apps.ps1 and
  EnneadTab-Certificate/docs/account-values.md. If the account/profile ever moves, change BOTH.
#>
[CmdletBinding()]
param(
  # Folder holding the built helper exes. Default: resolve relative to this script.
  [string]$ExeProductsDir = (Join-Path $PSScriptRoot '..\..\Apps\lib\ExeProducts'),
  # Optional explicit list of exe paths to sign; default = every *.exe in $ExeProductsDir.
  [string[]]$Files,
  # Re-sign files that already carry a Valid signature (default: skip them).
  [switch]$Force
)

$ErrorActionPreference = 'Stop'

# --- The 4 shared account values (EnneadTab-Certificate/docs/account-values.md) ---------------
$Endpoint      = 'https://eus.codesigning.azure.net/'   # East US, account 'EnneadTab'
$AccountName   = 'EnneadTab'
$ProfileName   = 'EnneadTab-PublicTrust'
$TimestampUrl  = 'http://timestamp.acs.microsoft.com'   # RFC3161 - NON-NEGOTIABLE (leaf rotates ~72h)

# --- UNSIGNED-BUT-GREEN gate ------------------------------------------------------------------
if (-not $env:AZURE_CLIENT_SECRET) {
  Write-Host 'sign-exeproducts: AZURE_CLIENT_SECRET absent on this runner - skipping signing (unsigned-but-green).' -ForegroundColor Yellow
  Write-Host '  (This is expected off the `signing` runner or after the signing campaign ends.)'
  exit 0
}

# --- Resolve target exes ----------------------------------------------------------------------
if (-not (Test-Path $ExeProductsDir)) { Write-Error "ExeProducts dir not found: $ExeProductsDir"; exit 1 }
if ($Files -and $Files.Count) {
  $targets = $Files | ForEach-Object { (Resolve-Path $_).Path }
} else {
  $targets = Get-ChildItem $ExeProductsDir -Filter *.exe -File | Select-Object -ExpandProperty FullName
}
if (-not $targets -or $targets.Count -eq 0) { Write-Host 'sign-exeproducts: no .exe targets found - nothing to do.'; exit 0 }

# Skip already-Valid signatures unless -Force (keeps repeat runs cheap; re-sign is otherwise safe).
if (-not $Force) {
  $targets = $targets | Where-Object {
    $s = Get-AuthenticodeSignature $_
    -not ($s.Status -eq 'Valid' -and $null -ne $s.TimeStamperCertificate)
  }
}
if (-not $targets -or $targets.Count -eq 0) { Write-Host 'sign-exeproducts: all targets already signed+timestamped - nothing to do.'; exit 0 }

Write-Host "sign-exeproducts: $($targets.Count) exe(s) to sign under $ExeProductsDir" -ForegroundColor Cyan

# --- Provision signtool.exe -------------------------------------------------------------------
# Prefer PATH, then the newest Windows Kits build, then the SDK BuildTools NuGet (no admin).
$signtool = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
if (-not $signtool) {
  $kit = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match '\\x64\\signtool.exe$' } |
    Sort-Object FullName -Descending | Select-Object -First 1
  if ($kit) { $signtool = $kit.FullName }
}

# --- Provision the Trusted Signing dlib (+ signtool fallback) from NuGet -----------------------
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$work = Join-Path ([IO.Path]::GetTempPath()) ('ennead-exesign-{0}' -f [guid]::NewGuid())
New-Item -ItemType Directory -Force -Path $work | Out-Null
try {
  Add-Type -AssemblyName System.IO.Compression.FileSystem

  # Trusted Signing dlib: bin\x64\ of Microsoft.Trusted.Signing.Client carries the dlib + deps.
  $tscVersion = '1.0.95'
  $tscNupkg = Join-Path $work 'tsc.nupkg'
  Invoke-WebRequest -UseBasicParsing -OutFile $tscNupkg `
    -Uri "https://api.nuget.org/v3-flatcontainer/microsoft.trusted.signing.client/$tscVersion/microsoft.trusted.signing.client.$tscVersion.nupkg"
  $zip = [IO.Compression.ZipFile]::OpenRead($tscNupkg)
  try {
    foreach ($e in $zip.Entries) {
      if ($e.FullName.ToLower().StartsWith('bin/x64/') -and -not $e.FullName.EndsWith('/')) {
        [IO.Compression.ZipFileExtensions]::ExtractToFile($e, (Join-Path $work ([IO.Path]::GetFileName($e.FullName))), $true)
      }
    }
  } finally { $zip.Dispose() }
  $dlib = Join-Path $work 'Azure.CodeSigning.Dlib.dll'
  if (-not (Test-Path $dlib)) { Write-Error 'Azure.CodeSigning.Dlib.dll not found after extracting Microsoft.Trusted.Signing.Client.'; exit 1 }

  # signtool fallback via the SDK BuildTools NuGet (bin\<ver>\x64\signtool.exe) if not found above.
  if (-not $signtool) {
    $sdkVersion = '10.0.22621.3233'
    $sdkNupkg = Join-Path $work 'sdk.nupkg'
    Invoke-WebRequest -UseBasicParsing -OutFile $sdkNupkg `
      -Uri "https://api.nuget.org/v3-flatcontainer/microsoft.windows.sdk.buildtools/$sdkVersion/microsoft.windows.sdk.buildtools.$sdkVersion.nupkg"
    $sdkDir = Join-Path $work 'sdk'
    [IO.Compression.ZipFile]::ExtractToDirectory($sdkNupkg, $sdkDir)
    $st = Get-ChildItem $sdkDir -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
      Where-Object { $_.FullName -match '\\x64\\signtool.exe$' } | Select-Object -First 1
    if ($st) { $signtool = $st.FullName }
  }
  if (-not $signtool) { Write-Error 'signtool.exe not found (PATH, Windows Kits, or SDK BuildTools NuGet).'; exit 1 }
  Write-Host "  signtool: $signtool"

  # metadata.json the dlib reads. MUST be BOM-less (System.Text.Json rejects a UTF-8 BOM). Auth is
  # the runner-local AZURE_* env (dlib uses DefaultAzureCredential -> EnvironmentCredential).
  $dmdf = Join-Path $work 'metadata.json'
  $dmdfJson = @{ Endpoint = $Endpoint; CodeSigningAccountName = $AccountName; CertificateProfileName = $ProfileName } | ConvertTo-Json
  [IO.File]::WriteAllText($dmdf, $dmdfJson, (New-Object System.Text.UTF8Encoding($false)))

  # --- Sign + verify each exe -----------------------------------------------------------------
  $bad = @()
  $ok = 0
  foreach ($exe in $targets) {
    Write-Host "sign: $exe" -ForegroundColor Yellow
    & $signtool sign /v /fd SHA256 /tr $TimestampUrl /td SHA256 /dlib $dlib /dmdf $dmdf $exe
    if ($LASTEXITCODE -ne 0) { Write-Warning "signtool failed on $exe (exit $LASTEXITCODE)"; $bad += $exe; continue }
    $sig = Get-AuthenticodeSignature $exe
    if ($sig.Status -ne 'Valid' -or $null -eq $sig.TimeStamperCertificate) {
      Write-Warning "$exe not signed+timestamped (status=$($sig.Status))"; $bad += $exe; continue
    }
    Write-Host "  ok status=$($sig.Status) signer=$($sig.SignerCertificate.Subject) timestamped=$($null -ne $sig.TimeStamperCertificate)" -ForegroundColor Green
    $ok++
  }

  Write-Host "sign-exeproducts: signed $ok, failed $($bad.Count)." -ForegroundColor Cyan
  if ($bad.Count) { Write-Error ("FAILED to sign+timestamp: " + ($bad -join ', ')); exit 1 }
}
finally {
  Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
}
