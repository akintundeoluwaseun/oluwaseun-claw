# Start S-CLAW in development mode (the desktop app starts the backend itself).
$ErrorActionPreference = 'Stop'
$desktop = Join-Path (Split-Path -Parent $PSScriptRoot) 'desktop'
Push-Location $desktop
npm start
Pop-Location
