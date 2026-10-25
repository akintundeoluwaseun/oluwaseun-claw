# Oluwaseun Claw - one-time developer setup on Windows 10 (PowerShell 5.1+)
# Run from the project root:   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
# Add -Chromium to also download Playwright's Chromium (only needed if you choose
# "Chromium" in Settings; the default browser is the Microsoft Edge built into Windows).
param([switch]$Chromium)
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

Write-Host '== Installing desktop dependencies (Electron)'
Push-Location $desktop
npm install --no-audit --no-fund
Pop-Location

Write-Host ''
Write-Host 'Setup complete. Next:'
Write-Host '  1. Install Ollama from https://ollama.com/download and run:  ollama pull qwen2.5:7b'
Write-Host '  2. Start the app:  powershell -ExecutionPolicy Bypass -File scripts\start.ps1'
