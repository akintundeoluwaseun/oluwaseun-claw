# Oluwaseun Claw - one-time developer setup on Windows 10 (PowerShell 5.1+)
# Run from the project root:   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#
# Besides Python and Electron, this fetches the two local engines Claw uses (no Ollama):
#   - llama.cpp's llama-server (MIT): the newest official Windows build, into backend\runtime\llama
#   - Tesseract OCR (Apache-2.0): the UB Mannheim Windows build, via winget
# Switches:
#   -Chromium               also download Playwright's Chromium (only if you pick "Chromium" in Settings)
#   -Gpu vulkan|cuda        use a GPU build of llama.cpp instead of the CPU build
#   -SkipEngine, -SkipOcr   leave those out
param(
  [switch]$Chromium,
  [ValidateSet('cpu', 'vulkan', 'cuda')][string]$Gpu = 'cpu',
  [switch]$SkipEngine,
  [switch]$SkipOcr
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$desktop = Join-Path $root 'desktop'

function Need($cmd, $hint) {
  if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "$cmd was not found. $hint" }
}

Need 'node' 'Install Node.js 22 LTS from https://nodejs.org and reopen PowerShell.'
Need 'npm'  'npm ships with Node.js 22.'

# Prefer the Python launcher with 3.12; fall back to any python on PATH.
$py = $null
if (Get-Command 'py' -ErrorAction SilentlyContinue) {
  & py -3.12 -c "import sys" 2>$null
  if ($LASTEXITCODE -eq 0) { $py = @('py', '-3.12') }
}
if (-not $py) {
  Need 'python' 'Install Python 3.12 (64-bit) from https://www.python.org and tick "Add to PATH".'
  $py = @('python')
}

Write-Host '== Creating Python environment in backend\.venv'
Push-Location $backend
$pyExe = $py[0]
$pyArgs = @($py | Select-Object -Skip 1)
if (-not (Test-Path '.venv')) { & $pyExe @pyArgs -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
if ($Chromium) {
  Write-Host '== Downloading Chromium for Playwright'
  & .\.venv\Scripts\python.exe -m playwright install chromium
}
Pop-Location

if (-not $SkipEngine) {
  # The file name is looked up in GitHub's release list at run time: no build number is hard-coded.
  Write-Host "== Fetching llama.cpp (llama-server, $Gpu build) from github.com/ggml-org/llama.cpp"
  $headers = @{ 'User-Agent' = 'oluwaseun-claw-setup' }
  if ($env:GITHUB_TOKEN) { $headers['Authorization'] = "Bearer $env:GITHUB_TOKEN" }  # build machines: avoids API rate limits
  $patterns = @{ cpu = '-bin-win-cpu-x64\.zip$'; vulkan = '-bin-win-vulkan-x64\.zip$'; cuda = '-bin-win-cuda[\d.-]*-x64\.zip$' }
  # llama.cpp publishes two kinds of release: version tags (v0.7.0) that carry only the source
  # archives, and per-commit build tags (b11900) that carry the Windows binaries. GitHub's
  # "latest" is often one of the source-only ones, so walk the list newest-first and take the
  # first release that really has the build we want.
  $rel = $null
  $asset = $null
  foreach ($page in 1..3) {
    $url = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=30&page=$page"
    $releases = @(Invoke-RestMethod -UseBasicParsing -Headers $headers $url)
    if ($releases.Count -eq 0) { break }
    foreach ($r in $releases) {
      $candidate = $r.assets | Where-Object { $_.name -match $patterns[$Gpu] -and $_.name -notmatch '^cudart' } | Select-Object -First 1
      if ($candidate) { $rel = $r; $asset = $candidate; break }
    }
    if ($asset) { break }
  }
  if (-not $asset) {
    throw "No Windows $Gpu build in the 90 most recent llama.cpp releases. Download one from https://github.com/ggml-org/llama.cpp/releases and unzip it into backend\runtime\llama, then run setup again with -SkipEngine."
  }
  Write-Host "   using llama.cpp release $($rel.tag_name)"
  $zip = Join-Path $env:TEMP $asset.name
  Invoke-WebRequest -UseBasicParsing $asset.browser_download_url -OutFile $zip
  if ($asset.digest -and $asset.digest -like 'sha256:*') {
    $want = $asset.digest.Substring(7).ToLower()
    $got = (Get-FileHash -Algorithm SHA256 $zip).Hash.ToLower()
    if ($want -ne $got) { Remove-Item $zip; throw 'The llama.cpp download was damaged (checksum mismatch). Run setup again.' }
    Write-Host '   checksum verified'
  } else {
    Write-Host '   (GitHub listed no checksum for this file)'
  }
  $dest = Join-Path $backend 'runtime\llama'
  if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
  Expand-Archive $zip -DestinationPath $dest
  Remove-Item $zip
  # Some builds unzip into a sub-folder: flatten so llama-server.exe sits directly in runtime\llama.
  $exe = Get-ChildItem $dest -Recurse -Filter 'llama-server.exe' | Select-Object -First 1
  if (-not $exe) { throw 'llama-server.exe was not in the downloaded build.' }
  if ($exe.DirectoryName -ne $dest) { Get-ChildItem $exe.DirectoryName | Move-Item -Destination $dest -Force }
  Set-Content (Join-Path $dest 'VERSION.txt') "llama.cpp $($rel.tag_name) $($asset.name)"
  & (Join-Path $dest 'llama-server.exe') --version
  Write-Host "   llama-server $($rel.tag_name) installed"
}

if (-not $SkipOcr) {
  $tessDefault = Join-Path $env:ProgramFiles 'Tesseract-OCR\tesseract.exe'
  if ((Get-Command 'tesseract' -ErrorAction SilentlyContinue) -or (Test-Path $tessDefault)) {
    Write-Host '== Tesseract OCR is already installed'
  } elseif (Get-Command 'winget' -ErrorAction SilentlyContinue) {
    Write-Host '== Installing Tesseract OCR (UB Mannheim build) with winget'
    winget install --id UB-Mannheim.TesseractOCR -e --accept-package-agreements --accept-source-agreements
  } else {
    Write-Host '!! Tesseract OCR is not installed and winget is not available.'
    Write-Host '   Install it from https://github.com/UB-Mannheim/tesseract/wiki'
    Write-Host '   (only scanned pages need it; everything else works without it).'
  }
}

Write-Host '== Installing desktop dependencies (Electron)'
Push-Location $desktop
npm install --no-audit --no-fund
Pop-Location

Write-Host ''
Write-Host 'Setup complete. Next:'
Write-Host '  1. Start the app:  powershell -ExecutionPolicy Bypass -File scripts\start.ps1'
Write-Host '  2. In Settings > Claw''s brain, download the recommended brain once,'
Write-Host '     or choose "Use a GGUF file I have".'
