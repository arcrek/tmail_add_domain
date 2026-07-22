from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess

import pytest


ROOT = Path(__file__).parents[1]
RELEASE = ROOT / "deploy" / "release.sh"
UNITS = (
    "tmail-policy.service",
    "tmail-api.service",
    "tmail-janitor.service",
    "tmail-janitor.timer",
)


def _fake_systemctl(tmp_path: Path):
    state = tmp_path / "systemctl-state"
    (state / "enabled").mkdir(parents=True)
    (state / "active").mkdir()
    (tmp_path / "runtime").mkdir(mode=0o700)
    command = tmp_path / "systemctl"
    command.write_text("""#!/usr/bin/env bash
set -eu
command=$1
shift || true
printf '%s %s\n' "$command" "$*" >> "$FAKE_SYSTEMD_STATE/log"
case "$command" in
    is-enabled) [ -e "$FAKE_SYSTEMD_STATE/enabled/$1" ] ;;
    is-active) [ -e "$FAKE_SYSTEMD_STATE/active/$1" ] ;;
    enable) for unit in "$@"; do : > "$FAKE_SYSTEMD_STATE/enabled/$unit"; done ;;
    disable) for unit in "$@"; do rm -f "$FAKE_SYSTEMD_STATE/enabled/$unit"; done ;;
    start) for unit in "$@"; do : > "$FAKE_SYSTEMD_STATE/active/$unit"; done ;;
    stop) for unit in "$@"; do rm -f "$FAKE_SYSTEMD_STATE/active/$unit"; done ;;
    restart)
        if [ "$1" = tmail-api.service ] && [ -e "$FAKE_SYSTEMD_STATE/fail-api" ]; then
            [ -f "$FAKE_RUNTIME_CONFIG" ] || exit 44
            exit 42
        fi
        : > "$FAKE_SYSTEMD_STATE/active/$1"
        ;;
    daemon-reload|status) ;;
    *) exit 2 ;;
esac
""")
    command.chmod(0o755)

    runuser = tmp_path / "runuser"
    runuser.write_text("""#!/usr/bin/env bash
set -eu
printf 'runuser %s\n' "$*" >> "$FAKE_SYSTEMD_STATE/log"
[ "$1" = -u ]
shift 2
[ "$1" = -- ]
shift
exec "$@"
""")
    runuser.chmod(0o755)
    return command, state


def _config_payload(jmap_token: str) -> str:
    return json.dumps({
        "jmap_url": "https://example.com/jmap/",
        "jmap_token": jmap_token,
        "mx_hostname": "mail.example.com",
        "catchall_address": "admin@example.com",
        "listen_addr": "127.0.0.1",
        "listen_port": 10030,
        "cache_file": "/var/lib/tmail-policy/domains.json",
        "api_token_secret": "a" * 32,
        "admin_password": "secret",
    })


def _release_tree(tmp_path: Path):
    stage = tmp_path / "stage"
    live = tmp_path / "live"
    systemd = tmp_path / "systemd"
    (stage / "deploy").mkdir(parents=True)
    (stage / "src").mkdir()
    systemd.mkdir()
    (stage / "version").write_text("new")
    (stage / "config.json").write_text(_config_payload("staged"))
    shutil.copy(ROOT / "src" / "config.py", stage / "src" / "config.py")
    for unit in UNITS:
        (stage / "deploy" / unit).write_text(f"new {unit}")
    return stage, live, systemd


def _run_release(stage, live, systemd, command, state):
    return subprocess.run(
        ["bash", str(RELEASE), str(stage), str(live)],
        capture_output=True,
        text=True,
        env=os.environ | {
            "TMAIL_SYSTEMD_DIR": str(systemd),
            "TMAIL_SYSTEMCTL": str(command),
            "FAKE_SYSTEMD_STATE": str(state),
            "FAKE_RUNTIME_CONFIG": str(state.parent / "runtime" / "config.json"),
            "PATH": f"{command.parent}:{os.environ['PATH']}",
            "TMAIL_CONFIG_DIR": str(state.parent / "runtime"),
        },
    )


def _state_files(state: Path, kind: str) -> set[str]:
    return {path.name for path in (state / kind).iterdir()}


@pytest.mark.parametrize("name", ["deploy.sh", "release.sh"])
def test_deploy_scripts_are_executable(name):
    mode = stat.S_IMODE((ROOT / "deploy" / name).stat().st_mode)
    assert mode == 0o755


def test_failed_upgrade_restores_units_release_and_prior_service_state(tmp_path):
    stage, live, systemd = _release_tree(tmp_path)
    command, state = _fake_systemctl(tmp_path)
    live.mkdir()
    (live / "version").write_text("old")

    old_units = {UNITS[0], UNITS[2], UNITS[3]}
    for unit in old_units:
        (systemd / unit).write_text(f"old {unit}")
    enabled = {UNITS[0], UNITS[3]}
    active = {UNITS[0], UNITS[2]}
    for unit in enabled:
        (state / "enabled" / unit).touch()
    for unit in active:
        (state / "active" / unit).touch()
    (state / "fail-api").touch()

    result = _run_release(stage, live, systemd, command, state)

    assert result.returncode == 42
    assert (live / "version").read_text() == "old"
    assert not stage.exists()
    assert {path.name for path in systemd.iterdir()} == old_units
    assert all((systemd / unit).read_text() == f"old {unit}" for unit in old_units)
    assert _state_files(state, "enabled") == enabled
    assert _state_files(state, "active") == active
    assert not list(tmp_path.glob(".tmail-policy.backup.*"))


def test_failed_fresh_install_removes_new_units_and_stops_services(tmp_path):
    stage, live, systemd = _release_tree(tmp_path)
    command, state = _fake_systemctl(tmp_path)
    (state / "fail-api").touch()

    result = _run_release(stage, live, systemd, command, state)

    assert result.returncode == 42
    assert not live.exists()
    assert not stage.exists()
    assert not list(systemd.iterdir())
    assert not _state_files(state, "enabled")
    assert not _state_files(state, "active")
    assert not list(tmp_path.glob(".tmail-policy.backup.*"))


def test_success_promotes_release_and_restarts_policy_before_api(tmp_path):
    stage, live, systemd = _release_tree(tmp_path)
    command, state = _fake_systemctl(tmp_path)

    result = _run_release(stage, live, systemd, command, state)

    assert result.returncode == 0, result.stderr
    assert (live / "version").read_text() == "new"
    log = (state / "log").read_text()
    assert log.index("restart tmail-policy.service") < log.index("restart tmail-api.service")
    assert _state_files(state, "enabled") == {
        "tmail-policy.service", "tmail-api.service", "tmail-janitor.timer",
    }
    assert not list(tmp_path.glob(".tmail-policy.backup.*"))


def test_release_migrates_snapshot_to_dedicated_runtime_config(tmp_path):
    stage, live, systemd = _release_tree(tmp_path)
    command, state = _fake_systemctl(tmp_path)
    snapshot = (stage / "config.json").read_text()

    result = _run_release(stage, live, systemd, command, state)

    assert result.returncode == 0, result.stderr
    runtime_config = state.parent / "runtime" / "config.json"
    assert runtime_config.read_text() == snapshot
    assert stat.S_IMODE(runtime_config.stat().st_mode) == 0o600
    assert not (live / "config.json").exists()


def test_release_preserves_existing_runtime_config(tmp_path):
    stage, live, systemd = _release_tree(tmp_path)
    command, state = _fake_systemctl(tmp_path)
    runtime_config = state.parent / "runtime" / "config.json"
    runtime_config.write_text("newer live config")
    runtime_config.chmod(0o600)

    result = _run_release(stage, live, systemd, command, state)

    assert result.returncode == 0, result.stderr
    assert runtime_config.read_text() == "newer live config"
    assert not (live / "config.json").exists()


def test_legacy_cutover_uses_config_updated_after_initial_snapshot(tmp_path):
    stage, live, systemd = _release_tree(tmp_path)
    command, state = _fake_systemctl(tmp_path)
    (stage / ".legacy-config").touch()
    live.mkdir()
    (live / "version").write_text("old")
    final_config = _config_payload("final")
    (live / "config.json").write_text(final_config)
    (state / "active" / "tmail-api.service").touch()

    result = _run_release(stage, live, systemd, command, state)

    assert result.returncode == 0, result.stderr
    runtime_config = state.parent / "runtime" / "config.json"
    assert runtime_config.read_text() == final_config
    log = (state / "log").read_text()
    state_capture = log.index("is-active tmail-api.service")
    stop = log.index("stop tmail-api.service")
    assert state_capture < stop < log.index(
        "runuser -u tmail-policy -- cat --",
    )


def test_invalid_final_legacy_snapshot_restores_previously_active_api(tmp_path):
    stage, live, systemd = _release_tree(tmp_path)
    command, state = _fake_systemctl(tmp_path)
    (stage / ".legacy-config").touch()
    live.mkdir()
    (live / "version").write_text("old")
    (live / "config.json").write_text("{}")
    (state / "active" / "tmail-api.service").touch()

    result = _run_release(stage, live, systemd, command, state)

    assert result.returncode == 1
    assert (state / "active" / "tmail-api.service").exists()
    assert (live / "version").read_text() == "old"
    assert not (state.parent / "runtime" / "config.json").exists()


def test_failed_release_removes_only_config_created_by_deployment(tmp_path):
    stage, live, systemd = _release_tree(tmp_path)
    command, state = _fake_systemctl(tmp_path)
    live.mkdir()
    (live / "version").write_text("old")
    (live / "config.json").write_text("legacy")
    (state / "fail-api").touch()

    result = _run_release(stage, live, systemd, command, state)

    assert result.returncode == 42
    assert not (state.parent / "runtime" / "config.json").exists()
    assert (live / "config.json").read_text() == "legacy"


def test_failed_release_never_removes_existing_runtime_config(tmp_path):
    stage, live, systemd = _release_tree(tmp_path)
    command, state = _fake_systemctl(tmp_path)
    runtime_config = state.parent / "runtime" / "config.json"
    runtime_config.write_text("newer live config")
    (state / "fail-api").touch()

    result = _run_release(stage, live, systemd, command, state)

    assert result.returncode == 42
    assert runtime_config.read_text() == "newer live config"


@pytest.mark.parametrize("name", ["install.sh", "deploy.sh"])
def test_deployment_entrypoints_use_tested_release_helper(name):
    script = (ROOT / "deploy" / name).read_text()
    assert "deploy/release.sh" in script
    assert 'bash "$STAGE_DIR/deploy/release.sh" "$STAGE_DIR" "$REMOTE_DIR"' in script


@pytest.mark.parametrize("name", ["install.sh", "deploy.sh"])
def test_staged_root_artifacts_are_not_writable_by_service(name):
    script = (ROOT / "deploy" / name).read_text()
    validation = script.index("python3 -m src.config validate-web")
    promotion = script.index('bash "$STAGE_DIR/deploy/release.sh"')

    root_ownership = script.index("chown -R root:root")
    directory_modes = script.index("-type d -exec chmod 755")
    artifact_modes = script.index("-type f ! -path")
    helper_mode = script.index("chmod 755", artifact_modes)
    assert root_ownership < validation
    assert directory_modes < validation
    assert artifact_modes < validation
    assert helper_mode < validation
    assert "config.json" in script[artifact_modes:helper_mode]

    service_owned_stage_lines = [
        line.strip()
        for line in script.splitlines()
        if "chown" in line
        and "tmail-policy:tmail-policy" in line
        and "STAGE_DIR" in line
    ]
    assert not service_owned_stage_lines


@pytest.mark.parametrize("name", ["install.sh", "deploy.sh"])
def test_entrypoints_snapshot_runtime_config_without_root_following_it(name):
    script = (ROOT / "deploy" / name).read_text()
    runtime = script.index('CONFIG_DIR="/var/lib/tmail-policy"')
    config_file = script.index('CONFIG_FILE="$CONFIG_DIR/config.json"', runtime)
    legacy = script.index("$REMOTE_DIR/config.json", config_file)
    supplied = script.index("Staging initial config", legacy)

    assert runtime < config_file < legacy < supplied
    assert "runuser -u tmail-policy -- cat --" in script
    assert "chown -R tmail-policy:tmail-policy /var/lib/tmail-policy" not in script


@pytest.mark.parametrize("name", ["install.sh", "deploy.sh"])
def test_entrypoints_mark_only_legacy_snapshots_for_cutover_refresh(name):
    script = (ROOT / "deploy" / name).read_text()
    legacy_branch = script.index("Snapshotting legacy production config")
    supplied_branch = script.index("Staging initial config", legacy_branch)

    assert ".legacy-config" in script[legacy_branch:supplied_branch]


def test_legacy_cutover_validation_runs_from_trusted_stage():
    script = RELEASE.read_text()
    assert (
        '(cd "$STAGE_DIR" && PYTHONPATH="$STAGE_DIR" /usr/bin/python3 -m src.config '
        'validate-web "$CUTOVER_CONFIG")'
    ) in script


@pytest.mark.parametrize(
    "name", ["tmail-policy.service", "tmail-api.service", "tmail-janitor.service"],
)
def test_service_units_use_dedicated_runtime_config(name):
    unit = (ROOT / "deploy" / name).read_text()
    assert "Environment=TMAIL_CONFIG=/var/lib/tmail-policy/config.json" in unit
    assert "Environment=TMAIL_CONFIG=/opt/tmail-policy/config.json" not in unit


@pytest.mark.parametrize("name", ["policy_daemon.py", "api_server.py", "email_janitor.py"])
def test_python_entrypoints_default_to_dedicated_runtime_config(name):
    source = (ROOT / "src" / name).read_text()
    assert 'os.environ.get("TMAIL_CONFIG", "/var/lib/tmail-policy/config.json")' in source


@pytest.mark.parametrize("name", ["install.sh", "deploy.sh"])
def test_privileged_scripts_do_not_use_predictable_temp_files(name):
    script = (ROOT / "deploy" / name).read_text()
    assert "/tmp/tmail-requirements.txt" not in script
    assert "/tmp/main.cf.dedup" not in script
