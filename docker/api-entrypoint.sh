#!/bin/sh
set -eu

runtime_config=${TMAIL_CONFIG:-/var/lib/tmail-policy/config.json}
seed_config=${TMAIL_CONFIG_SEED:-/run/tmail/config.json}
runtime_dir=$(dirname "$runtime_config")

mkdir -p "$runtime_dir"

if [ -L "$runtime_config" ]; then
    echo "ERROR: runtime config must not be a symlink: $runtime_config" >&2
    exit 1
fi

if [ ! -e "$runtime_config" ]; then
    if [ ! -f "$seed_config" ]; then
        echo "ERROR: config seed not found: $seed_config" >&2
        exit 1
    fi
    python3 -m src.config install-runtime "$runtime_config" < "$seed_config"
elif [ ! -f "$runtime_config" ]; then
    echo "ERROR: runtime config must be a regular file: $runtime_config" >&2
    exit 1
fi

if [ "$(id -u)" -eq 0 ]; then
    chown tmail:tmail "$runtime_dir" "$runtime_config"
    chmod 0700 "$runtime_dir"
    chmod 0600 "$runtime_config"
    exec gosu tmail "$@"
fi

exec "$@"
