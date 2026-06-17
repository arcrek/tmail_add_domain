#!/usr/bin/env bash
set -euo pipefail

SERVER="${1:?Usage: ./deploy.sh user@hostname}"
REMOTE_DIR="/opt/tmail-policy"

echo "==> Installing Python dependencies on remote"
ssh "$SERVER" "pip3 install dnspython httpx"

echo "==> Creating remote directories"
ssh "$SERVER" "mkdir -p $REMOTE_DIR /var/lib/tmail-policy"

echo "==> Uploading daemon source"
ssh "$SERVER" "mkdir -p $REMOTE_DIR/src"
scp src/__init__.py src/config.py src/domain_cache.py src/mx_checker.py \
    src/jmap_client.py src/policy_daemon.py \
    "$SERVER:$REMOTE_DIR/src/"

echo "==> Uploading systemd unit"
scp deploy/tmail-policy.service "$SERVER:/etc/systemd/system/"

echo "==> Creating service user (idempotent)"
ssh "$SERVER" "id tmail-policy &>/dev/null || useradd -r -s /sbin/nologin tmail-policy"

echo "==> Setting permissions"
ssh "$SERVER" "
  chown -R tmail-policy:tmail-policy $REMOTE_DIR /var/lib/tmail-policy
  [ -f $REMOTE_DIR/config.json ] && chmod 600 $REMOTE_DIR/config.json || true
"

echo "==> Enabling and restarting service"
ssh "$SERVER" "systemctl daemon-reload && systemctl enable tmail-policy && systemctl restart tmail-policy"

echo "==> Status"
ssh "$SERVER" "systemctl status tmail-policy --no-pager -l"
