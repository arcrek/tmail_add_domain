#!/usr/bin/env bash
# Run this script directly on the VPS from the project root.
# Must be run as root: sudo bash deploy/install.sh  (or: sh deploy/install.sh)
[ -n "$BASH_VERSION" ] || exec bash "$0" "$@"
set -euo pipefail

REMOTE_DIR="/opt/tmail-policy"
SERVICE_FILE="deploy/tmail-policy.service"

[ "$(id -u)" -eq 0 ] || { echo "ERROR: must be run as root (use sudo)"; exit 1; }
[ -f config.json ] || { echo "ERROR: config.json not found. Copy config.example.json to config.json and fill in your API token first."; exit 1; }
[ -f "$SERVICE_FILE" ] || { echo "ERROR: run from project root (deploy/tmail-policy.service not found)"; exit 1; }

echo "==> Installing Python dependencies"
pip3 install -r requirements.txt

echo "==> Creating directories"
mkdir -p "$REMOTE_DIR/src" /var/lib/tmail-policy

echo "==> Copying source files"
cp src/__init__.py src/config.py src/domain_cache.py src/mx_checker.py \
   src/jmap_client.py src/policy_daemon.py "$REMOTE_DIR/src/"

echo "==> Copying config"
cp config.json "$REMOTE_DIR/config.json"

echo "==> Installing systemd unit"
cp "$SERVICE_FILE" /etc/systemd/system/tmail-policy.service

echo "==> Creating service user (idempotent)"
id tmail-policy &>/dev/null || useradd -r -s /sbin/nologin tmail-policy

echo "==> Setting permissions"
chown -R tmail-policy:tmail-policy "$REMOTE_DIR" /var/lib/tmail-policy
chmod 600 "$REMOTE_DIR/config.json"

echo "==> Enabling and starting policy daemon"
systemctl daemon-reload
systemctl enable tmail-policy
systemctl restart tmail-policy

echo "==> Status"
systemctl status tmail-policy --no-pager -l

# ── Postfix setup ──────────────────────────────────────────────────────────────

echo "==> Installing Postfix"
DEBIAN_FRONTEND=noninteractive apt-get install -y postfix

echo "==> Backing up /etc/postfix/main.cf"
cp /etc/postfix/main.cf /etc/postfix/main.cf.bak

echo "==> Applying tmail-policy config snippet"
# Remove any previous tmail-policy block to keep install idempotent
sed -i '/# --- tmail-policy additions ---/,/# --- end tmail-policy additions ---/d' /etc/postfix/main.cf
cat deploy/postfix_main_snippet.cf >> /etc/postfix/main.cf

echo "==> Installing accepted_domains PCRE map"
cp deploy/accepted_domains /etc/postfix/accepted_domains

echo "==> Validating Postfix config"
postfix check

echo "==> Restarting Postfix"
systemctl restart postfix
systemctl status postfix --no-pager -l

echo ""
echo "==> MANUAL STEP REQUIRED: move Stalwart off port 25"
echo "    Postfix now owns :25. If Stalwart still binds 0.0.0.0:25, they will conflict."
echo "    Edit your Stalwart config and change its SMTP listener to 127.0.0.1:25 (or disable it)."
echo "    Confirm LMTP listener is enabled on 127.0.0.1:24."
echo "    Then: systemctl restart stalwart-mail"
echo "    Verify: ss -tlnp | grep -E ':25|:24'"
