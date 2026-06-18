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

echo "==> Installing Postfix and PCRE support"
POSTFIX_HOSTNAME=$(python3 -c "import json; print(json.load(open('config.json'))['mx_hostname'])")
POSTFIX_DOMAIN=$(echo "$POSTFIX_HOSTNAME" | cut -d. -f2-)

# Write /etc/mailname before apt runs so the post-install script uses the right hostname
echo "$POSTFIX_HOSTNAME" > /etc/mailname

# If a broken previous install left a bad main.cf, patch it so dpkg --configure succeeds
if [ -f /etc/postfix/main.cf ]; then
    sed -i "s/^myhostname = .*/myhostname = ${POSTFIX_HOSTNAME}/" /etc/postfix/main.cf
    sed -i "s/^mydomain = .*/mydomain = ${POSTFIX_DOMAIN}/" /etc/postfix/main.cf
fi

echo "postfix postfix/main_mailer_type select Internet Site" | debconf-set-selections
echo "postfix postfix/mailname string ${POSTFIX_HOSTNAME}" | debconf-set-selections
DEBIAN_FRONTEND=noninteractive apt-get install -y postfix postfix-pcre

echo "==> Backing up /etc/postfix/main.cf"
cp /etc/postfix/main.cf /etc/postfix/main.cf.bak

echo "==> Installing accepted_domains PCRE map"
cp deploy/accepted_domains /etc/postfix/accepted_domains

echo "==> Cleaning up any duplicate keys from previous installs"
awk '!seen[$1]++' /etc/postfix/main.cf > /tmp/main.cf.dedup && mv /tmp/main.cf.dedup /etc/postfix/main.cf

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
systemctl enable 'postfix@-.service'   # instance unit is enabled-runtime by default; make it permanent
systemctl restart postfix
systemctl status postfix --no-pager -l

# ── Stalwart coexistence fix ───────────────────────────────────────────────────
# Stalwart's default unit has Conflicts=postfix.service, which causes systemd to
# send SIGINT to Stalwart every time Postfix starts.  Remove that conflict (the
# port clash it guarded against is gone — Stalwart listens on 2525, not 25) and
# add Wants=network-online.target so port binding waits for the NIC.

STALWART_UNIT=/etc/systemd/system/stalwart.service
if [ -f "$STALWART_UNIT" ]; then
    echo "==> Patching $STALWART_UNIT (remove Conflicts=postfix, add Wants=network-online)"
    sed -i 's/Conflicts=postfix\.service //' "$STALWART_UNIT"
    sed -i 's/Conflicts=postfix\.service$//' "$STALWART_UNIT"
    grep -q 'Wants=network-online.target' "$STALWART_UNIT" || \
        sed -i '/^After=network-online.target/a Wants=network-online.target' "$STALWART_UNIT"
    systemctl daemon-reload
    systemctl restart stalwart
    systemctl status stalwart --no-pager -l
fi

echo ""
echo "==> Verifying port ownership"
ss -tlnp | grep -E ':25|:2525' || true

echo ""
echo "==> Done. Postfix on :25, Stalwart receiving on :2525."
echo "    Test: swaks --to test@yourdomain.com --server 127.0.0.1"
echo ""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║  MANUAL STEP REQUIRED — Stalwart web UI                        ║"
echo "║                                                                  ║"
echo "║  Stalwart's default config requires SMTP auth on port 2525,    ║"
echo "║  which blocks Postfix from delivering mail internally.          ║"
echo "║                                                                  ║"
echo "║  Fix:                                                            ║"
echo "║  1. Open http://<server-ip>:8080/admin                         ║"
echo "║  2. Navigate to: Settings → MTA → Inbound Sessions → AUTH      ║"
echo "║  3. Find: Require Authentication                                ║"
echo "║  4. Change the condition from:  local_port != 25               ║"
echo "║                            to:  local_port == 465              ║"
echo "║  5. Save                                                         ║"
echo "║  6. Run: systemctl restart stalwart                             ║"
echo "║                                                                  ║"
echo "║  This makes auth required only on :465 (submissions), not on   ║"
echo "║  :2525 (internal Postfix relay) or :25 (MX delivery).          ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
