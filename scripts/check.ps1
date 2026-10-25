# Run every automated check: backend tests, desktop syntax + unit tests, end-to-end app test.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$failed = $false

Push-Location (Join-Path $root 'backend')
Write-Host '== Backend: compile'
& .\.venv\Scripts\python.exe -m compileall -q claw tests; if ($LASTEXITCODE) { $failed = $true }
Write-Host '== Backend: tests'
& .\.venv\Scripts\python.exe -m pytest -q; if ($LASTEXITCODE) { $failed = $true }
Pop-Location

Push-Location (Join-Path $root 'desktop')
Write-Host '== Desktop: syntax'
npm run -s check; if ($LASTEXITCODE) { $failed = $true }
Write-Host '== Desktop: unit tests'
npm test; if ($LASTEXITCODE) { $failed = $true }
Write-Host '== Desktop: end-to-end (opens the app window briefly)'
node tests\e2e.mjs; if ($LASTEXITCODE) { $failed = $true }
Pop-Location

if ($failed) { Write-Host 'SOME CHECKS FAILED' -ForegroundColor Red; exit 1 }
Write-Host 'All checks passed' -ForegroundColor Green
