#!/usr/bin/env bash
# Run this script directly on the VPS from the project root.
# Must be run as root: sudo bash deploy/install.sh  (or: sh deploy/install.sh)
[ -n "$BASH_VERSION" ] || exec bash "$0" "$@"
set -euo pipefail

REMOTE_DIR="/opt/tmail-policy"
POLICY_SERVICE_FILE="deploy/tmail-policy.service"
API_SERVICE_FILE="deploy/tmail-api.service"

[ "$(id -u)" -eq 0 ] || { echo "ERROR: must be run as root (use sudo)"; exit 1; }
[ -f config.json ] || { echo "ERROR: config.json not found. Copy config.example.json to config.json and fill in your API token first."; exit 1; }
[ -f "$POLICY_SERVICE_FILE" ] || { echo "ERROR: run from project root (deploy/tmail-policy.service not found)"; exit 1; }
[ -f "$API_SERVICE_FILE" ] || { echo "ERROR: deploy/tmail-api.service not found"; exit 1; }

echo "==> Installing Python dependencies"
pip3 install -r requirements.txt

echo "==> Building frontend"
npm --prefix frontend ci
npm --prefix frontend run build

echo "==> Creating directories"
mkdir -p "$REMOTE_DIR/src" "$REMOTE_DIR/frontend/dist" /var/lib/tmail-policy

echo "==> Copying source files"
cp src/*.py "$REMOTE_DIR/src/"
cp -r frontend/dist/. "$REMOTE_DIR/frontend/dist/"

if [ -f "$REMOTE_DIR/config.json" ]; then
    echo "==> Preserving existing production config"
else
    echo "==> Installing config"
    cp config.json "$REMOTE_DIR/config.json"
fi

CONFIG_ERRORS=$(python3 - "$REMOTE_DIR/config.json" <<'PY'
import json
import sys

with open(sys.argv[1]) as handle:
    config = json.load(handle)
secret = config.get("api_token_secret")
password = config.get("admin_password")
if not isinstance(secret, str) or len(secret) < 32:
    print("api_token_secret")
if not isinstance(password, str) or not password.strip():
    print("admin_password")
PY
)
if [ -n "$CONFIG_ERRORS" ]; then
    if [[ "$CONFIG_ERRORS" == *api_token_secret* ]]; then
        echo "ERROR: api_token_secret must contain at least 32 characters. Generate one with:"
        echo "       python3 -c 'import secrets; print(secrets.token_urlsafe(32))'"
    fi
    if [[ "$CONFIG_ERRORS" == *admin_password* ]]; then
        echo "ERROR: admin_password must not be empty."
    fi
    exit 1
fi

echo "==> Installing systemd units"
cp "$POLICY_SERVICE_FILE" /etc/systemd/system/tmail-policy.service
cp "$API_SERVICE_FILE" /etc/systemd/system/tmail-api.service
cp deploy/tmail-janitor.service /etc/systemd/system/tmail-janitor.service
cp deploy/tmail-janitor.timer /etc/systemd/system/tmail-janitor.timer

echo "==> Creating service user (idempotent)"
id tmail-policy &>/dev/null || useradd -r -s /sbin/nologin tmail-policy

echo "==> Setting permissions"
chown -R tmail-policy:tmail-policy "$REMOTE_DIR" /var/lib/tmail-policy
chmod 600 "$REMOTE_DIR/config.json"

echo "==> Enabling and starting services"
systemctl daemon-reload
systemctl enable tmail-policy tmail-api
systemctl restart tmail-policy
systemctl restart tmail-api

echo "==> Enabling email janitor timer (runs daily at 03:00)"
systemctl enable tmail-janitor.timer
systemctl start tmail-janitor.timer

echo "==> Status"
systemctl status tmail-policy --no-pager -l
systemctl status tmail-api --no-pager -l

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
    "smtpd_recipient_restrictions = permit_mynetworks, check_policy_service inet:127.0.0.1:10030, reject"

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
