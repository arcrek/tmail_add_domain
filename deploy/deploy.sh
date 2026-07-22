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
    deploy/tmail-janitor.timer deploy/release.sh "$SERVER:$STAGE_DIR/deploy/"

if ssh "$SERVER" "test -f '$REMOTE_DIR/config.json'"; then
    echo "==> Staging existing production config"
    ssh "$SERVER" "install -m 600 '$REMOTE_DIR/config.json' '$STAGE_DIR/config.json'"
else
    echo "==> Staging initial config"
    scp config.json "$SERVER:$STAGE_DIR/config.json.upload"
    ssh "$SERVER" "install -m 600 '$STAGE_DIR/config.json.upload' '$STAGE_DIR/config.json' && rm -f '$STAGE_DIR/config.json.upload'"
fi

echo "==> Securing staged release"
ssh "$SERVER" "chown -R root:root '$STAGE_DIR' && find '$STAGE_DIR' -type d -exec chmod 755 {} + && find '$STAGE_DIR' -type f ! -path '$STAGE_DIR/config.json' -exec chmod 644 {} + && chmod 755 '$STAGE_DIR/deploy/release.sh' && chmod 600 '$STAGE_DIR/config.json'"

echo "==> Validating staged web config"
ssh "$SERVER" "cd '$STAGE_DIR' && PYTHONPATH='$STAGE_DIR' python3 -m src.config validate-web '$STAGE_DIR/config.json'"

echo "==> Preparing Python dependencies"
ssh "$SERVER" "pip3 install -r '$STAGE_DIR/requirements.txt'"

echo "==> Preparing service data ownership"
ssh "$SERVER" "id tmail-policy &>/dev/null || useradd -r -s /sbin/nologin tmail-policy"
ssh "$SERVER" "mkdir -p /var/lib/tmail-policy && chown -R tmail-policy:tmail-policy /var/lib/tmail-policy"

echo "==> Promoting staged release"
ssh "$SERVER" bash "$STAGE_DIR/deploy/release.sh" "$STAGE_DIR" "$REMOTE_DIR"

STAGE_DIR=""
echo "==> Deployment complete"
