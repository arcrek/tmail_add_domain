#!/usr/bin/env bash
set -euo pipefail

SERVER="${1:?Usage: ./deploy.sh user@hostname}"
REMOTE_DIR="/opt/tmail-policy"
STAGE_DIR=""

[ -f config.json ] || { echo "ERROR: config.json not found. Copy config.example.json to config.json and configure it first."; exit 1; }

cleanup() {
    status=$?
    trap - EXIT
    if [[ "$STAGE_DIR" =~ ^/opt/\.tmail-policy\.stage\.[A-Za-z0-9]+$ ]]; then
        ssh "$SERVER" "rm -rf -- '$STAGE_DIR'" || true
    fi
    exit "$status"
}
trap cleanup EXIT

echo "==> Building frontend"
npm --prefix frontend ci
npm --prefix frontend run build

echo "==> Creating secure remote stage"
STAGE_DIR=$(ssh "$SERVER" "mktemp -d /opt/.tmail-policy.stage.XXXXXX")
[[ "$STAGE_DIR" =~ ^/opt/\.tmail-policy\.stage\.[A-Za-z0-9]+$ ]] || { echo "ERROR: invalid remote stage path"; exit 1; }
ssh "$SERVER" "mkdir -p '$STAGE_DIR/src' '$STAGE_DIR/frontend/dist' '$STAGE_DIR/deploy'"

echo "==> Uploading staged release"
scp requirements.txt "$SERVER:$STAGE_DIR/requirements.txt"
scp src/*.py "$SERVER:$STAGE_DIR/src/"
scp -r frontend/dist/. "$SERVER:$STAGE_DIR/frontend/dist/"
scp deploy/tmail-policy.service deploy/tmail-api.service deploy/tmail-janitor.service \
    deploy/tmail-janitor.timer "$SERVER:$STAGE_DIR/deploy/"

if ssh "$SERVER" "test -f '$REMOTE_DIR/config.json'"; then
    echo "==> Staging existing production config"
    ssh "$SERVER" "install -m 600 '$REMOTE_DIR/config.json' '$STAGE_DIR/config.json'"
else
    echo "==> Staging initial config"
    scp config.json "$SERVER:$STAGE_DIR/config.json.upload"
    ssh "$SERVER" "install -m 600 '$STAGE_DIR/config.json.upload' '$STAGE_DIR/config.json' && rm -f '$STAGE_DIR/config.json.upload'"
fi

echo "==> Validating staged web config"
ssh "$SERVER" "cd '$STAGE_DIR' && PYTHONPATH='$STAGE_DIR' python3 -m src.config validate-web '$STAGE_DIR/config.json'"

echo "==> Preparing Python dependencies"
ssh "$SERVER" "pip3 install -r '$STAGE_DIR/requirements.txt'"

echo "==> Preparing service ownership"
ssh "$SERVER" "id tmail-policy &>/dev/null || useradd -r -s /sbin/nologin tmail-policy; mkdir -p /var/lib/tmail-policy; chown -R tmail-policy:tmail-policy '$STAGE_DIR' /var/lib/tmail-policy; chmod 600 '$STAGE_DIR/config.json'"

echo "==> Promoting staged release"
ssh "$SERVER" bash -s -- "$STAGE_DIR" "$REMOTE_DIR" <<'REMOTE'
set -euo pipefail

STAGE_DIR=$1
REMOTE_DIR=$2
BACKUP_DIR=$(mktemp -d /opt/.tmail-policy.backup.XXXXXX)
PROMOTED=0

cleanup() {
    status=$?
    trap - EXIT
    set +e
    if [ "$status" -ne 0 ] && [ "$PROMOTED" -eq 1 ]; then
        mv "$REMOTE_DIR" "$BACKUP_DIR/failed"
        if [ -e "$BACKUP_DIR/release" ]; then
            mv "$BACKUP_DIR/release" "$REMOTE_DIR"
            systemctl daemon-reload
            systemctl restart tmail-policy
            systemctl restart tmail-api
        fi
    fi
    [[ "$BACKUP_DIR" == /opt/.tmail-policy.backup.* ]] && rm -rf -- "$BACKUP_DIR"
    exit "$status"
}
trap cleanup EXIT

cp "$STAGE_DIR/deploy/tmail-policy.service" /etc/systemd/system/tmail-policy.service
cp "$STAGE_DIR/deploy/tmail-api.service" /etc/systemd/system/tmail-api.service
cp "$STAGE_DIR/deploy/tmail-janitor.service" /etc/systemd/system/tmail-janitor.service
cp "$STAGE_DIR/deploy/tmail-janitor.timer" /etc/systemd/system/tmail-janitor.timer

if [ -e "$REMOTE_DIR" ]; then
    mv "$REMOTE_DIR" "$BACKUP_DIR/release"
fi
if ! mv "$STAGE_DIR" "$REMOTE_DIR"; then
    [ ! -e "$BACKUP_DIR/release" ] || mv "$BACKUP_DIR/release" "$REMOTE_DIR"
    exit 1
fi
PROMOTED=1

systemctl daemon-reload
systemctl enable tmail-policy tmail-api tmail-janitor.timer
systemctl restart tmail-policy
systemctl restart tmail-api
systemctl start tmail-janitor.timer
systemctl status tmail-policy tmail-api --no-pager -l

PROMOTED=0
rm -rf -- "$BACKUP_DIR"
BACKUP_DIR=""
REMOTE

STAGE_DIR=""
echo "==> Deployment complete"
