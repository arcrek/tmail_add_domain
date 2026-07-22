#!/usr/bin/env bash
set -euo pipefail

SERVER="${1:?Usage: ./deploy.sh user@hostname}"
REMOTE_DIR="/opt/tmail-policy"
CONFIG_DIR="/var/lib/tmail-policy"
CONFIG_FILE="$CONFIG_DIR/config.json"
LEGACY_CONFIG="$REMOTE_DIR/config.json"
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

echo "==> Preparing service runtime directory"
ssh "$SERVER" "id tmail-policy &>/dev/null || useradd -r -s /sbin/nologin tmail-policy"
ssh "$SERVER" "mkdir -p '$CONFIG_DIR' && chown tmail-policy:tmail-policy '$CONFIG_DIR' && chmod 700 '$CONFIG_DIR'"

echo "==> Uploading staged release"
scp requirements.txt "$SERVER:$STAGE_DIR/requirements.txt"
scp src/*.py "$SERVER:$STAGE_DIR/src/"
scp -r frontend/dist/. "$SERVER:$STAGE_DIR/frontend/dist/"
scp deploy/tmail-policy.service deploy/tmail-api.service deploy/tmail-janitor.service \
    deploy/tmail-janitor.timer deploy/release.sh "$SERVER:$STAGE_DIR/deploy/"

if ssh "$SERVER" "test -L '$CONFIG_FILE' || test -e '$CONFIG_FILE'"; then
    echo "==> Snapshotting existing runtime config"
    ssh "$SERVER" "runuser -u tmail-policy -- cat -- '$CONFIG_FILE' > '$STAGE_DIR/config.json' && chmod 600 '$STAGE_DIR/config.json'"
elif ssh "$SERVER" "test -L '$LEGACY_CONFIG' || test -e '$LEGACY_CONFIG'"; then
    echo "==> Snapshotting legacy production config"
    ssh "$SERVER" "runuser -u tmail-policy -- cat -- '$LEGACY_CONFIG' > '$STAGE_DIR/config.json' && chmod 600 '$STAGE_DIR/config.json' && touch '$STAGE_DIR/.legacy-config'"
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

echo "==> Promoting staged release"
ssh "$SERVER" bash "$STAGE_DIR/deploy/release.sh" "$STAGE_DIR" "$REMOTE_DIR"

STAGE_DIR=""
echo "==> Deployment complete"
