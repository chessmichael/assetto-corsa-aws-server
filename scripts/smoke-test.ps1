<#
.SYNOPSIS
  Real end-to-end smoke test: `terraform apply`, verify the box boots + registers
  with SSM + finishes installing AssettoServer, then ALWAYS `terraform destroy`.

  Costs a few cents (minutes of a t3.medium) and needs AWS credentials. It does
  NOT need Assetto Corsa content or the game — it checks infra health, not a live
  session (a live /INFO needs `ac deploy` with real content, which is the manual
  step).

.PARAMETER Yes
  Skip the confirmation prompt (for unattended runs).

.EXAMPLE
  pwsh ./scripts/smoke-test.ps1
#>
param([switch]$Yes)

$ErrorActionPreference = "Stop"
$tf = Join-Path (Split-Path -Parent $PSScriptRoot) "terraform"

foreach ($t in @("terraform", "aws")) {
    if (-not (Get-Command $t -ErrorAction SilentlyContinue)) {
        Write-Error "$t not found on PATH."; exit 1
    }
}

if (-not $Yes) {
    Write-Host "This creates REAL AWS resources (EC2 + EIP + S3), checks them, then destroys them." -ForegroundColor Yellow
    Write-Host "Estimated cost: a few cents. AWS credentials must be configured." -ForegroundColor Yellow
    if ((Read-Host "Type 'yes' to proceed") -ne "yes") { Write-Host "Aborted."; exit 1 }
}

Push-Location $tf
$applied = $false
$pass = $false
try {
    terraform init -input=false
    if ($LASTEXITCODE -ne 0) { throw "init failed" }
    Write-Host "Applying (first boot takes a few minutes)..." -ForegroundColor Cyan
    terraform apply -auto-approve
    if ($LASTEXITCODE -ne 0) { throw "apply failed" }
    $applied = $true

    $iid    = (terraform output -raw instance_id).Trim()
    $region = (terraform output -raw region).Trim()
    Write-Host "Instance $iid in $region. Waiting for SSM to register..." -ForegroundColor Cyan

    # 1) Wait until the instance is managed by SSM (agent dials out shortly after boot).
    $online = $false
    for ($i = 0; $i -lt 30; $i++) {
        $ping = aws ssm describe-instance-information --region $region `
            --filters "Key=InstanceIds,Values=$iid" `
            --query "InstanceInformationList[0].PingStatus" --output text 2>$null
        if ($ping -eq "Online") { $online = $true; break }
        Start-Sleep -Seconds 10
    }
    if (-not $online) { throw "instance never registered with SSM" }
    Write-Host "SSM online. Waiting for setup to finish + AssettoServer to install..." -ForegroundColor Cyan

    # 2) Poll an install health check over SSM until HEALTHY or timeout (~5 min).
    $check = '{"commands":["test -x /opt/ac/server/AssettoServer && grep -q \"setup complete\" /var/log/ac-setup.log && echo HEALTHY || echo NOTREADY"]}'
    $paramFile = New-TemporaryFile
    Set-Content -Path $paramFile -Value $check -Encoding utf8

    for ($i = 0; $i -lt 10; $i++) {
        $cid = aws ssm send-command --region $region --instance-ids $iid `
            --document-name AWS-RunShellScript --parameters "file://$paramFile" `
            --query "Command.CommandId" --output text
        Start-Sleep -Seconds 6
        $out = aws ssm get-command-invocation --region $region `
            --command-id $cid --instance-id $iid `
            --query "StandardOutputContent" --output text 2>$null
        if ($out -match "HEALTHY") { $pass = $true; break }
        Write-Host "  not ready yet (attempt $($i + 1)/10)..."
        Start-Sleep -Seconds 24
    }
    Remove-Item $paramFile -ErrorAction SilentlyContinue

    if ($pass) {
        Write-Host "`nPASS: box booted, SSM-managed, AssettoServer installed." -ForegroundColor Green
        Write-Host "(To verify a live session, run: ac init; ac sync; ac config; ac deploy)"
    } else {
        Write-Host "`nFAIL: install did not report healthy in time. Check /var/log/ac-setup.log via SSM." -ForegroundColor Red
    }
}
finally {
    if ($applied) {
        Write-Host "`nDestroying test resources..." -ForegroundColor Cyan
        terraform destroy -auto-approve
    }
    Pop-Location
}

if (-not $pass) { exit 1 }
