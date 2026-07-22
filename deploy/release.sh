#!/usr/bin/env bash
set -euo pipefail

STAGE_DIR="${1:?staged release path required}"
REMOTE_DIR="${2:?live release path required}"
SYSTEMD_DIR="${TMAIL_SYSTEMD_DIR:-/etc/systemd/system}"
SYSTEMCTL="${TMAIL_SYSTEMCTL:-systemctl}"
CONFIG_DIR="${TMAIL_CONFIG_DIR:-/var/lib/tmail-policy}"
CONFIG_FILE="$CONFIG_DIR/config.json"
UNITS=(
    tmail-policy.service
    tmail-api.service
    tmail-janitor.service
    tmail-janitor.timer
)
BACKUP_DIR=$(mktemp -d "$(dirname "$REMOTE_DIR")/.tmail-policy.backup.XXXXXX")
OLD_RELEASE=0
PROMOTED=0
UNITS_BACKED_UP=0
CONFIG_CREATED=0

cleanup() {
    status=$?
    trap - EXIT
    set +e
    rollback_failed=0

    if [ "$status" -ne 0 ] && [ "$UNITS_BACKED_UP" -eq 1 ]; then
        for unit in "${UNITS[@]}"; do
            "$SYSTEMCTL" stop "$unit" || rollback_failed=1
            "$SYSTEMCTL" disable "$unit" || rollback_failed=1
        done

        if [ "$PROMOTED" -eq 1 ] && [ -e "$REMOTE_DIR" ]; then
            mv "$REMOTE_DIR" "$BACKUP_DIR/failed" || rollback_failed=1
        fi
        if [ "$OLD_RELEASE" -eq 1 ] && [ -e "$BACKUP_DIR/release" ]; then
            mv "$BACKUP_DIR/release" "$REMOTE_DIR" || rollback_failed=1
        fi
        if [ "$CONFIG_CREATED" -eq 1 ]; then
            runuser -u tmail-policy -- rm -f -- "$CONFIG_FILE" || rollback_failed=1
        fi

        for unit in "${UNITS[@]}"; do
            rm -f -- "$SYSTEMD_DIR/$unit" || rollback_failed=1
            if [ -e "$BACKUP_DIR/units/$unit" ] || [ -L "$BACKUP_DIR/units/$unit" ]; then
                cp -a -- "$BACKUP_DIR/units/$unit" "$SYSTEMD_DIR/$unit" || rollback_failed=1
            fi
        done
        "$SYSTEMCTL" daemon-reload || rollback_failed=1

        for unit in "${UNITS[@]}"; do
            if [ -e "$BACKUP_DIR/state/$unit.enabled" ]; then
                "$SYSTEMCTL" enable "$unit" || rollback_failed=1
            else
                "$SYSTEMCTL" disable "$unit" || rollback_failed=1
            fi
            if [ -e "$BACKUP_DIR/state/$unit.active" ]; then
                "$SYSTEMCTL" start "$unit" || rollback_failed=1
            else
                "$SYSTEMCTL" stop "$unit" || rollback_failed=1
            fi
        done
    fi

    if [ "$rollback_failed" -eq 0 ]; then
        rm -rf -- "$BACKUP_DIR"
    else
        echo "ERROR: rollback incomplete; recovery data retained at $BACKUP_DIR" >&2
    fi
    exit "$status"
}
trap cleanup EXIT

mkdir -p "$BACKUP_DIR/units" "$BACKUP_DIR/state"
for unit in "${UNITS[@]}"; do
    [ -f "$STAGE_DIR/deploy/$unit" ]
    if [ -e "$SYSTEMD_DIR/$unit" ] || [ -L "$SYSTEMD_DIR/$unit" ]; then
        cp -a -- "$SYSTEMD_DIR/$unit" "$BACKUP_DIR/units/$unit"
    fi
    if "$SYSTEMCTL" is-enabled "$unit" >/dev/null 2>&1; then
        : > "$BACKUP_DIR/state/$unit.enabled"
    fi
    if "$SYSTEMCTL" is-active "$unit" >/dev/null 2>&1; then
        : > "$BACKUP_DIR/state/$unit.active"
    fi
done
UNITS_BACKED_UP=1

for unit in "${UNITS[@]}"; do
    rm -f -- "$SYSTEMD_DIR/$unit"
    install -m 644 "$STAGE_DIR/deploy/$unit" "$SYSTEMD_DIR/$unit"
done

if [ -e "$REMOTE_DIR" ]; then
    mv "$REMOTE_DIR" "$BACKUP_DIR/release"
    OLD_RELEASE=1
fi
mv "$STAGE_DIR" "$REMOTE_DIR"
PROMOTED=1
if [ -L "$CONFIG_FILE" ] || [ -e "$CONFIG_FILE" ]; then
    :
else
    runuser -u tmail-policy -- /usr/bin/python3 "$REMOTE_DIR/src/config.py" \
        install-runtime "$CONFIG_FILE" < "$REMOTE_DIR/config.json"
    CONFIG_CREATED=1
fi
rm -f -- "$REMOTE_DIR/config.json"

"$SYSTEMCTL" daemon-reload
"$SYSTEMCTL" enable tmail-policy.service tmail-api.service tmail-janitor.timer
"$SYSTEMCTL" restart tmail-policy.service
"$SYSTEMCTL" restart tmail-api.service
"$SYSTEMCTL" start tmail-janitor.timer
"$SYSTEMCTL" status tmail-policy.service tmail-api.service --no-pager -l
