#!/usr/bin/env bash
# Real end-to-end smoke test: apply -> verify boot/SSM/install -> always destroy.
# Costs a few cents and needs AWS creds. No Assetto Corsa content/game required.
# Usage: ./scripts/smoke-test.sh [--yes]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF="$SCRIPT_DIR/../terraform"

for t in terraform aws; do
  command -v "$t" >/dev/null || { echo "$t not found on PATH"; exit 1; }
done

if [ "${1:-}" != "--yes" ]; then
  echo "This creates REAL AWS resources (EC2 + EIP + S3), checks them, then destroys them (~a few cents)."
  read -r -p "Type 'yes' to proceed: " ans
  [ "$ans" = "yes" ] || { echo "Aborted."; exit 1; }
fi

cd "$TF"
applied=false
pass=false
cleanup() { if $applied; then echo "Destroying test resources..."; terraform destroy -auto-approve; fi; }
trap cleanup EXIT

terraform init -input=false
echo "Applying (first boot takes a few minutes)..."
terraform apply -auto-approve
applied=true

IID=$(terraform output -raw instance_id)
REGION=$(terraform output -raw region)
echo "Instance $IID in $REGION; waiting for SSM to register..."

online=false
for _ in $(seq 1 30); do
  ping=$(aws ssm describe-instance-information --region "$REGION" \
    --filters "Key=InstanceIds,Values=$IID" \
    --query "InstanceInformationList[0].PingStatus" --output text 2>/dev/null || true)
  [ "$ping" = "Online" ] && { online=true; break; }
  sleep 10
done
$online || { echo "Instance never registered with SSM"; exit 1; }
echo "SSM online; waiting for setup to finish + AssettoServer install..."

PARAMS=$(mktemp)
cat > "$PARAMS" <<'JSON'
{"commands":["test -x /opt/ac/server/AssettoServer && grep -q \"setup complete\" /var/log/ac-setup.log && echo HEALTHY || echo NOTREADY"]}
JSON

for i in $(seq 1 10); do
  CID=$(aws ssm send-command --region "$REGION" --instance-ids "$IID" \
    --document-name AWS-RunShellScript --parameters "file://$PARAMS" \
    --query "Command.CommandId" --output text)
  sleep 6
  OUT=$(aws ssm get-command-invocation --region "$REGION" \
    --command-id "$CID" --instance-id "$IID" \
    --query "StandardOutputContent" --output text 2>/dev/null || true)
  case "$OUT" in *HEALTHY*) pass=true; break;; esac
  echo "  not ready yet (attempt $i/10)..."
  sleep 24
done
rm -f "$PARAMS"

if $pass; then
  echo "PASS: box booted, SSM-managed, AssettoServer installed."
  echo "(To verify a live session: ac init; ac sync; ac config; ac deploy)"
else
  echo "FAIL: install did not report healthy in time."
fi
$pass
