<#
.SYNOPSIS
  Static checks for the Terraform config: formatting + validation.
  Touches no AWS account (uses `init -backend=false`).

.EXAMPLE
  pwsh ./scripts/check-terraform.ps1
#>
$ErrorActionPreference = "Stop"
$tf = Join-Path (Split-Path -Parent $PSScriptRoot) "terraform"

if (-not (Get-Command terraform -ErrorAction SilentlyContinue)) {
    Write-Error "terraform not found on PATH. Install it from developer.hashicorp.com/terraform/install"
    exit 1
}

Push-Location $tf
try {
    Write-Host "terraform fmt -check ..." -ForegroundColor Cyan
    terraform fmt -check -recursive
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Formatting issues above. Run 'terraform fmt -recursive' to fix."
        throw "fmt check failed"
    }

    Write-Host "terraform init (no backend) ..." -ForegroundColor Cyan
    terraform init -backend=false -input=false
    if ($LASTEXITCODE -ne 0) { throw "init failed" }

    Write-Host "terraform validate ..." -ForegroundColor Cyan
    terraform validate
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
