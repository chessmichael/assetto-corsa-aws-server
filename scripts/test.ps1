<#
.SYNOPSIS
  Install dev deps and run the offline + mocked-AWS test suite (no AWS account,
  no Assetto Corsa content needed).

.EXAMPLE
  pwsh ./scripts/test.ps1
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

# Find a REAL python (skip the Windows Store alias under WindowsApps).
$py = $null
foreach ($c in @("py", "python", "python3")) {
    $cmd = Get-Command $c -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notmatch "WindowsApps") { $py = $c; break }
}
if (-not $py) {
    Write-Error "No real Python found. Install Python 3.9+ from python.org (the Windows Store stub won't work)."
    exit 1
}

Push-Location $root
try {
    Write-Host "Installing package + test deps with $py ..." -ForegroundColor Cyan
    & $py -m pip install -e ".[test]"
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

    Write-Host "Running pytest ..." -ForegroundColor Cyan
    & $py -m pytest
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
