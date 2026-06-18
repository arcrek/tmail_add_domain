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
POSTFIX_HOSTNAME=$(grep '^myhostname' deploy/postfix_main_snippet.cf | awk '{print $3}')
POSTFIX_DOMAIN=$(grep '^mydomain' deploy/postfix_main_snippet.cf | awk '{print $3}')

# Write /etc/mailname before apt runs so the post-install script uses the right hostname
echo "$POSTFIX_HOSTNAME" > /etc/mailname

# If a broken previous install left a bad main.cf, patch it so dpkg --configure succeeds
if [ -f /etc/postfix/main.cf ]; then
    sed -i "s/^myhostname = .*/myhostname = ${POSTFIX_HOSTNAME}/" /etc/postfix/main.cf
    sed -i "s/^mydomain = .*/mydomain = ${POSTFIX_DOMAIN}/" /etc/postfix/main.cf
fi

echo "postfix postfix/main_mailer_type select Internet Site" | debconf-set-selections
echo "postfix postfix/mailname string ${POSTFIX_HOSTNAME}" | debconf-set-selections
DEBIAN_FRONTEND=noninteractive apt-get install -y postfix

echo "==> Backing up /etc/postfix/main.cf"
cp /etc/postfix/main.cf /etc/postfix/main.cf.bak

echo "==> Installing accepted_domains PCRE map"
cp deploy/accepted_domains /etc/postfix/accepted_domains

echo "==> Applying Postfix config (postconf -e, no duplicates)"
postconf -e \
    "myhostname = ${POSTFIX_HOSTNAME}" \
    "mydomain = ${POSTFIX_DOMAIN}" \
    "myorigin = \$myhostname" \
    "inet_interfaces = all" \
    "inet_protocols = ipv4" \
    "mydestination = " \
    "local_recipient_maps = " \
    "local_transport = error:local delivery disabled" \
    "virtual_transport = smtp:127.0.0.1:2525" \
    "virtual_mailbox_domains = pcre:/etc/postfix/accepted_domains" \
    "mynetworks = 127.0.0.0/8" \
    "relay_domains = " \
    "smtpd_recipient_restrictions = permit_mynetworks, check_policy_service inet:127.0.0.1:10030, permit"

echo "==> Validating Postfix config"
postfix check

echo "==> Restarting Postfix"
systemctl restart postfix
systemctl status postfix --no-pager -l

echo ""
echo "==> Verifying port ownership"
ss -tlnp | grep -E ':25|:2525' || true

echo ""
echo "==> Done. Postfix on :25, Stalwart receiving on :2525."
echo "    Test: swaks --to test@yourdomain.com --server 127.0.0.1"
