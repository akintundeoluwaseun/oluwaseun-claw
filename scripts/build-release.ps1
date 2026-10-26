# Oluwaseun Claw - build the Windows installers (Standard and/or Pro).
# Run on Windows 10/11 x64 after scripts\setup.ps1, from the project root:
#   powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1 -Edition Standard
#   powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1 -Edition Pro
#
# Needs: Inno Setup 6 (winget install JRSoftware.InnoSetup), and the edition's brain already
# downloaded once in Claw (Settings > Claw's brain) so its files and checksums are on disk.
# The brain is copied from %APPDATA%\OluwaseunClaw\models\<id> unless -ModelDir is given.
param(
  [ValidateSet('Standard', 'Pro')][string]$Edition = 'Standard',
  [string]$ModelDir = '',
  [string]$TesseractDir = (Join-Path $env:ProgramFiles 'Tesseract-OCR'),
  [switch]$NoBrain,  # build the small installer that downloads the brain on first run
  [int]$SliceMB = 0   # >0: split the installer into parts of this size (GitHub releases allow 2 GB per file)
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$desktop = Join-Path $root 'desktop'
$stage = Join-Path $root "build\stage-$($Edition.ToLower())"
$out = Join-Path $root 'build\installers'
$modelId = @{ Standard = 'qwen3-vl-4b'; Pro = 'qwen3-vl-8b' }[$Edition]
$version = (Get-Content (Join-Path $desktop 'package.json') | ConvertFrom-Json).version

function Step($t) { Write-Host "== $t" }
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Force $stage, $out | Out-Null

Step 'Freezing the backend (PyInstaller)'
& (Join-Path $backend '.venv\Scripts\python.exe') -m pip install -q pyinstaller==6.16.0
& (Join-Path $backend '.venv\Scripts\python.exe') (Join-Path $backend 'packaging\build_backend.py') --out (Join-Path $stage '_frozen')
if ($LASTEXITCODE -ne 0) { throw 'Backend build failed.' }
Move-Item (Join-Path $stage '_frozen\claw-backend') (Join-Path $stage 'backend')
Remove-Item -Recurse -Force (Join-Path $stage '_frozen')

Step 'Copying the AI engine (llama.cpp)'
$engineSrc = Join-Path $backend 'runtime\llama'
if (-not (Test-Path (Join-Path $engineSrc 'llama-server.exe'))) { throw 'llama-server.exe not found. Run scripts\setup.ps1 first.' }
Copy-Item -Recurse $engineSrc (Join-Path $stage 'engine')

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
if (-not $NoBrain) {
  Step "Copying the $Edition brain ($modelId)"
  if (-not $ModelDir) { $ModelDir = Join-Path $env:APPDATA "OluwaseunClaw\models\$modelId" }
  $manifest = Join-Path $ModelDir 'manifest.json'
  if (-not (Test-Path $manifest)) { throw "No downloaded $Edition brain in $ModelDir. Download it once in Claw, or pass -ModelDir." }
  $m = Get-Content $manifest | ConvertFrom-Json
  if (-not $m.verified) { throw 'That brain was not checksum-verified when downloaded; download it again before shipping it.' }
  if ($m.license -notin @('apache-2.0', 'mit')) { throw "Brain licence '$($m.license)' is not on the allowed list for bundling." }
  Copy-Item -Recurse $ModelDir (Join-Path $stage "models\$modelId")
}

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
$label = if ($NoBrain) { "$Edition-NoBrain" } else { $Edition }
$isccArgs = @("/DEdition=$label", "/DAppDir=$appDir", "/DVersion=$version", "/DOutDir=$out")
if ($SliceMB -gt 0) { $isccArgs += "/DSliceBytes=$([int64]$SliceMB * 1024 * 1024)" }
& $iscc @isccArgs (Join-Path $root 'packaging\claw.iss')
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup failed.' }

Get-ChildItem $out | Where-Object { $_.Name -like "*$label*" } | ForEach-Object {
  $h = (Get-FileHash -Algorithm SHA256 $_.FullName).Hash.ToLower()
  "$h  $($_.Name)" | Tee-Object -Append (Join-Path $out 'SHA256SUMS.txt')
}
Write-Host "Done. Installers are in $out"
