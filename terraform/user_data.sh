# NOTE: no shebang here on purpose. main.tf prepends "#!/bin/bash" plus the
# AC_BUCKET / AC_REGION / AC_AS_VERSION exports, then this file. Keep this file
# free of Terraform interpolation so there is no "${}" escaping to worry about.
set -uxo pipefail
exec > >(tee -a /var/log/ac-setup.log) 2>&1
echo "=== ac-server setup starting $(date -u) ==="

export DEBIAN_FRONTEND=noninteractive

# ---------------------------------------------------------------------------
# 1. Persist the few settings the helper scripts need, so they can stay static.
# ---------------------------------------------------------------------------
cat > /etc/ac.env <<EOF
AC_BUCKET=${AC_BUCKET}
AC_REGION=${AC_REGION}
EOF

# ---------------------------------------------------------------------------
# 2. System dependencies.
#    - i386 libs: native acServer is a 32-bit ELF binary.
#    - libicu: .NET self-contained runtime (AssettoServer) globalization.
# ---------------------------------------------------------------------------
dpkg --add-architecture i386
apt-get update -y
apt-get install -y --no-install-recommends \
  curl unzip jq ca-certificates tzdata \
  lib32gcc-s1 libc6:i386 libstdc++6:i386 \
  libicu74

# ---------------------------------------------------------------------------
# 3. AWS CLI v2 (needed for `aws s3 sync` on the box). SSM agent is already
#    preinstalled on the Ubuntu 24.04 AMI via snap.
# ---------------------------------------------------------------------------
if ! command -v aws >/dev/null 2>&1; then
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
  unzip -q /tmp/awscliv2.zip -d /tmp
  /tmp/aws/install
fi

mkdir -p /opt/ac/server/cfg /opt/ac/server/content/cars /opt/ac/server/content/tracks

# ---------------------------------------------------------------------------
# 4. Install AssettoServer (self-contained linux-x64) into /opt/ac/server.
#    Flatten any single top-level folder so the binary lands at a known path.
# ---------------------------------------------------------------------------
if [ "${AC_AS_VERSION}" = "latest" ]; then
  AS_URL=$(curl -fsSL https://api.github.com/repos/compujuckel/AssettoServer/releases/latest \
    | jq -r '.assets[] | select(.name=="assetto-server-linux-x64.tar.gz") | .browser_download_url')
else
  AS_URL="https://github.com/compujuckel/AssettoServer/releases/download/${AC_AS_VERSION}/assetto-server-linux-x64.tar.gz"
fi

if [ -n "${AS_URL}" ] && curl -fsSL "${AS_URL}" -o /tmp/as.tar.gz; then
  rm -rf /tmp/as && mkdir -p /tmp/as
  tar -xzf /tmp/as.tar.gz -C /tmp/as
  if [ "$(ls -1 /tmp/as | wc -l)" = "1" ] && [ -d "/tmp/as/$(ls -1 /tmp/as)" ]; then
    cp -a /tmp/as/*/. /opt/ac/server/
  else
    cp -a /tmp/as/. /opt/ac/server/
  fi
  chmod +x /opt/ac/server/AssettoServer || true
  echo "AssettoServer installed from ${AS_URL}"
else
  echo "WARNING: could not download AssettoServer from '${AS_URL}'"
fi

# ---------------------------------------------------------------------------
# 5. Optionally install vanilla acServer. Its Linux binary cannot be downloaded
#    anonymously, so we pick it up from s3://BUCKET/bin/acServer if you have put
#    one there (see README). AssettoServer works without this.
# ---------------------------------------------------------------------------
if aws s3 cp "s3://${AC_BUCKET}/bin/acServer" /opt/ac/server/acServer --region "${AC_REGION}" 2>/dev/null; then
  chmod +x /opt/ac/server/acServer
  echo "acServer installed from s3://${AC_BUCKET}/bin/acServer"
else
  echo "acServer not found in S3 (vanilla backend disabled until you upload one)"
fi

# ---------------------------------------------------------------------------
# 6. Helper scripts.
#    ac-presync : pull latest cfg + content from S3 (idempotent, runs before
#                 every service start so reboots/start-stop self-refresh).
#    ac-update  : pull, then enable+restart whichever backend .backend names.
# ---------------------------------------------------------------------------
cat > /usr/local/bin/ac-presync <<'EOF'
#!/bin/bash
set -a; . /etc/ac.env; set +a
# extra_cfg.yml is auto-generated and owned by AssettoServer; exclude it so the
# --delete sync never removes the server's own copy.
aws s3 sync "s3://$AC_BUCKET/server/cfg"     /opt/ac/server/cfg     --delete --exclude "extra_cfg.yml" --only-show-errors --region "$AC_REGION" || true
aws s3 sync "s3://$AC_BUCKET/server/content" /opt/ac/server/content --delete --only-show-errors --region "$AC_REGION" || true
aws s3 cp   "s3://$AC_BUCKET/server/.backend" /opt/ac/server/.backend --only-show-errors --region "$AC_REGION" || true
EOF
chmod +x /usr/local/bin/ac-presync

cat > /usr/local/bin/ac-update <<'EOF'
#!/bin/bash
set -e
/usr/local/bin/ac-presync
BACKEND=$(tr -d '[:space:]' < /opt/ac/server/.backend 2>/dev/null || true)
[ -z "$BACKEND" ] && BACKEND=assettoserver
systemctl stop assettoserver acserver 2>/dev/null || true
if [ "$BACKEND" = "acserver" ]; then
  if [ ! -x /opt/ac/server/acServer ]; then
    echo "ERROR: acserver backend selected but /opt/ac/server/acServer is missing"; exit 1
  fi
  systemctl disable assettoserver 2>/dev/null || true
  systemctl enable acserver
  systemctl restart acserver
else
  systemctl disable acserver 2>/dev/null || true
  systemctl enable assettoserver
  systemctl restart assettoserver
fi
echo "backend '$BACKEND' restarted"
EOF
chmod +x /usr/local/bin/ac-update

# ---------------------------------------------------------------------------
# 7. systemd units. Both refresh content from S3 before starting. Neither is
#    enabled now — the first `ac deploy` selects and enables a backend.
# ---------------------------------------------------------------------------
cat > /etc/systemd/system/assettoserver.service <<'EOF'
[Unit]
Description=AssettoServer (Assetto Corsa)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/ac/server
ExecStartPre=/usr/local/bin/ac-presync
ExecStart=/opt/ac/server/AssettoServer
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/acserver.service <<'EOF'
[Unit]
Description=Assetto Corsa dedicated server (vanilla acServer)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/ac/server
ExecStartPre=/usr/local/bin/ac-presync
ExecStart=/opt/ac/server/acServer
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
echo "=== ac-server setup complete $(date -u) ==="
