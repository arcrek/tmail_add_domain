#!/usr/bin/env bash
set -euo pipefail

SERVER="${1:?Usage: ./deploy.sh user@hostname}"
[ -f config.json ] || { echo "ERROR: config.json not found. Copy config.example.json to config.json and fill in your API token first."; exit 1; }
REMOTE_DIR="/opt/tmail-policy"

echo "==> Building frontend"
npm --prefix frontend ci
npm --prefix frontend run build

echo "==> Installing Python dependencies on remote"
scp requirements.txt "$SERVER:/tmp/tmail-requirements.txt"
ssh "$SERVER" "pip3 install -r /tmp/tmail-requirements.txt"

echo "==> Creating remote directories"
ssh "$SERVER" "mkdir -p $REMOTE_DIR/src $REMOTE_DIR/frontend /var/lib/tmail-policy"

echo "==> Uploading source and frontend"
scp src/*.py "$SERVER:$REMOTE_DIR/src/"
scp -r frontend/dist "$SERVER:$REMOTE_DIR/frontend/"

if ssh "$SERVER" "test -f $REMOTE_DIR/config.json"; then
    echo "==> Preserving existing production config"
else
    echo "==> Uploading initial config"
    scp config.json "$SERVER:$REMOTE_DIR/config.json"
fi

CONFIG_ERRORS=$(ssh "$SERVER" python3 - "$REMOTE_DIR/config.json" <<'PY'
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

echo "==> Uploading systemd units"
scp deploy/tmail-policy.service deploy/tmail-api.service deploy/tmail-janitor.service \
    deploy/tmail-janitor.timer "$SERVER:/etc/systemd/system/"

echo "==> Creating service user (idempotent)"
ssh "$SERVER" "id tmail-policy &>/dev/null || useradd -r -s /sbin/nologin tmail-policy"

echo "==> Setting permissions"
ssh "$SERVER" "
  chown -R tmail-policy:tmail-policy $REMOTE_DIR /var/lib/tmail-policy
  [ -f $REMOTE_DIR/config.json ] && chmod 600 $REMOTE_DIR/config.json || true
"

echo "==> Enabling and restarting services"
ssh "$SERVER" "systemctl daemon-reload && systemctl enable tmail-policy tmail-api && systemctl restart tmail-policy && systemctl restart tmail-api && systemctl enable --now tmail-janitor.timer"

echo "==> Status"
ssh "$SERVER" "systemctl status tmail-policy tmail-api --no-pager -l"
