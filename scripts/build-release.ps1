# S-CLAW - build the Windows installers.
#
# There is one application and two packaging profiles:
#
#   -Edition Online   Claw Online. The interface, the backend, the computer-control
#                     tools and every safety check, with NO inference engine and NO
#                     model weights. Thinking happens on the Claw service, whose
#                     address is written into the build. Small installer; needs the
#                     internet. Requires -ServiceUrl.
#
#   -Edition Local    Claw Local. The same application plus llama.cpp and one brain,
#                     so it thinks on the computer and keeps working with the network
#                     switched off. Large installer; -Brain picks which model.
#
# Run on Windows 10/11 x64 after scripts\setup.ps1, from the project root:
#   powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1 -Edition Online -ServiceUrl https://...
#   powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1 -Edition Local -Brain Standard -SliceMB 1900
#
# Needs: Inno Setup 6 (winget install JRSoftware.InnoSetup). For -Edition Local the brain
# must already have been downloaded once in Claw (Settings > Claw's brain) so its files and
# checksums are on disk; it is copied from %APPDATA%\S-CLAW\models\<id> unless
# -ModelDir is given.
param(
  [ValidateSet('Online', 'Local')][string]$Edition = 'Local',
  [ValidateSet('Tiny', 'Light', 'Standard', 'Pro')][string]$Brain = 'Standard',
  # Claw Online only. The service this build talks to; no user ever types it.
  [string]$ServiceUrl = '',
  [string]$ServiceToken = '',
  [string]$ModelDir = '',
  [string]$TesseractDir = (Join-Path $env:ProgramFiles 'Tesseract-OCR'),
  [switch]$NoBrain,  # Local only: ship without the brain and download it on first run
  [int]$SliceMB = 0   # >0: split the installer into parts of this size (GitHub releases allow 2 GB per file)
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$desktop = Join-Path $root 'desktop'
$stage = Join-Path $root "build\stage-$($Edition.ToLower())"
$out = Join-Path $root 'build\installers'
$modelId = @{ Tiny = 'qwen3-0.6b'; Light = 'qwen3-vl-2b'; Standard = 'qwen3-vl-4b'; Pro = 'qwen3-vl-8b' }[$Brain]
$version = (Get-Content (Join-Path $desktop 'package.json') | ConvertFrom-Json).version
$online = $Edition -eq 'Online'

if ($online) {
  if (-not $ServiceUrl) { throw 'Claw Online needs -ServiceUrl: the address of the Claw service it thinks with. There is no default, and this build must not guess one.' }
  if ($ServiceUrl -notmatch '^https://') { throw 'The Claw service address must be https: the instructions, the documents and the token all travel over it.' }
  if ($SliceMB -gt 0) { throw 'Claw Online carries no model weights, so there is nothing to split. Drop -SliceMB.' }
}

function Step($t) { Write-Host "== $t" }
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Force $stage, $out | Out-Null

Step 'Freezing the backend (PyInstaller)'
& (Join-Path $backend '.venv\Scripts\python.exe') -m pip install -q pyinstaller==6.16.0
& (Join-Path $backend '.venv\Scripts\python.exe') (Join-Path $backend 'packaging\build_backend.py') --out (Join-Path $stage '_frozen')
if ($LASTEXITCODE -ne 0) { throw 'Backend build failed.' }
Move-Item (Join-Path $stage '_frozen\claw-backend') (Join-Path $stage 'backend')
Remove-Item -Recurse -Force (Join-Path $stage '_frozen')

# The engine is the thing that makes Claw Local large and Claw Online small. Leaving the
# folder present but empty keeps electron-builder's extraResources list the same for both.
New-Item -ItemType Directory -Force (Join-Path $stage 'engine') | Out-Null
if ($online) {
  Step 'Skipping the AI engine (Claw Online thinks on the Claw service)'
} else {
  Step 'Copying the AI engine (llama.cpp)'
  $engineSrc = Join-Path $backend 'runtime\llama'
  if (-not (Test-Path (Join-Path $engineSrc 'llama-server.exe'))) { throw 'llama-server.exe not found. Run scripts\setup.ps1 first.' }
  Copy-Item -Recurse (Join-Path $engineSrc '*') (Join-Path $stage 'engine')
  # llama-server needs the Microsoft Visual C++ runtime. Build machines have it; many home
  # PCs do not, and without it the engine dies before printing a word ("not connecting").
  # Microsoft allows these DLLs to be shipped next to the program that uses them.
  foreach ($dll in 'vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll', 'vcomp140.dll') {
    $src = Join-Path $env:WINDIR "System32\$dll"
    if ((Test-Path $src) -and -not (Test-Path (Join-Path $stage "engine\$dll"))) { Copy-Item $src (Join-Path $stage 'engine') }
  }
  if (-not (Test-Path (Join-Path $stage 'engine\vcruntime140.dll'))) { throw 'vcruntime140.dll was not found to ship with the engine.' }
}

Step 'Copying Tesseract OCR (English + page orientation data, configs)'
if (-not (Test-Path (Join-Path $TesseractDir 'tesseract.exe'))) { throw "Tesseract not found in $TesseractDir. Run scripts\setup.ps1 or pass -TesseractDir." }
$tess = Join-Path $stage 'tesseract'
New-Item -ItemType Directory -Force (Join-Path $tess 'tessdata') | Out-Null
Copy-Item (Join-Path $TesseractDir '*.exe'), (Join-Path $TesseractDir '*.dll') $tess
# Language data plus configs\ (tsv, pdf output modes) and pdf.ttf (searchable PDFs): without them
# Tesseract silently falls back to plain text, which Claw now reports as "OCR data incomplete".
foreach ($f in 'eng.traineddata', 'osd.traineddata', 'pdf.ttf') { Copy-Item (Join-Path $TesseractDir "tessdata\$f") (Join-Path $tess 'tessdata') }
foreach ($d in 'configs', 'tessconfigs') {
  $src = Join-Path $TesseractDir "tessdata\$d"
  if (Test-Path $src) { Copy-Item -Recurse $src (Join-Path $tess "tessdata\$d") }
}
if (-not (Test-Path (Join-Path $tess 'tessdata\configs\tsv'))) { throw 'tessdata\configs\tsv is missing from the Tesseract install.' }
Get-ChildItem $TesseractDir -Filter '*.txt' | Where-Object { $_.Name -match 'LICENSE|COPYING|AUTHORS' } | Copy-Item -Destination $tess

New-Item -ItemType Directory -Force (Join-Path $stage 'models') | Out-Null
if ($online) {
  Step 'Skipping the brain (Claw Online ships no model weights)'
} elseif (-not $NoBrain) {
  Step "Copying the $Brain brain ($modelId)"
  if (-not $ModelDir) { $ModelDir = Join-Path $env:APPDATA "S-CLAW\models\$modelId" }
  $manifest = Join-Path $ModelDir 'manifest.json'
  if (-not (Test-Path $manifest)) { throw "No downloaded $Brain brain in $ModelDir. Download it once in Claw, or pass -ModelDir." }
  $m = Get-Content $manifest | ConvertFrom-Json
  if (-not $m.verified) { throw 'That brain was not checksum-verified when downloaded; download it again before shipping it.' }
  if ($m.license -notin @('apache-2.0', 'mit')) { throw "Brain licence '$($m.license)' is not on the allowed list for bundling." }
  Copy-Item -Recurse $ModelDir (Join-Path $stage "models\$modelId")
}

Step "Writing the edition profile ($Edition)"
# claw/edition.py reads this at run time. It is the single switch between the two
# editions: everything else in the app is identical.
# Worked out first: "if" is a statement, not something a hashtable value can be.
$bundled = if ($online -or $NoBrain) { '' } else { $modelId }
$profileJson = [ordered]@{
  id              = $Edition.ToLower()
  name            = "Claw $Edition"
  local_inference = (-not $online)
  service_url     = $ServiceUrl
  service_token   = $ServiceToken
  bundled_model   = $bundled
}
$profileJson | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $stage 'edition.json')
if ($ServiceToken) { Write-Host '   (a service token was built in; it is not printed here)' }

Step 'Packaging the app (electron-builder, unpacked)'
Push-Location $desktop
$env:CLAW_STAGE = $stage
$env:CLAW_EDITION = $Edition
npx electron-builder --config electron-builder.config.js --win dir
if ($LASTEXITCODE -ne 0) { Pop-Location; throw 'electron-builder failed.' }
Pop-Location
$appDir = Join-Path $root "build\app-$($Edition.ToLower())\win-unpacked"
# The app folder now holds its own copy of the brain; free the staging copy (disk space on build machines).
Remove-Item -Recurse -Force (Join-Path $stage 'models') -ErrorAction SilentlyContinue

Step 'Making the installer (Inno Setup)'
$iscc = @((Get-Command 'iscc' -ErrorAction SilentlyContinue).Source,
          (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
          (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) { throw 'Inno Setup 6 not found. Install it: winget install JRSoftware.InnoSetup' }
$label = if ($online) { 'Online' } elseif ($NoBrain) { 'Local-NoBrain' } else { "Local-$Brain" }
$isccArgs = @("/DEdition=$label", "/DAppDir=$appDir", "/DVersion=$version", "/DOutDir=$out")
if ($SliceMB -gt 0) { $isccArgs += "/DSliceBytes=$([int64]$SliceMB * 1024 * 1024)" }
& $iscc @isccArgs (Join-Path $root 'packaging\claw.iss')
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup failed.' }

Get-ChildItem $out | Where-Object { $_.Name -like "*$label*" } | ForEach-Object {
  $h = (Get-FileHash -Algorithm SHA256 $_.FullName).Hash.ToLower()
  "$h  $($_.Name)" | Tee-Object -Append (Join-Path $out 'SHA256SUMS.txt')
}
# Measured, not estimated: the brief asks for the actual sizes of both editions.
$built = Get-ChildItem $out | Where-Object { $_.Name -like "*$label*" }
$totalMB = [math]::Round((($built | Measure-Object Length -Sum).Sum) / 1MB, 1)
foreach ($f in $built) { Write-Host ("   {0,-52} {1,8:N1} MB" -f $f.Name, ($f.Length / 1MB)) }
Write-Host "S-CLAW ${Edition}: $($built.Count) file(s), $totalMB MB in total"
Write-Host "Done. Installers are in $out"
