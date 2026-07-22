from __future__ import annotations

import os
from pathlib import Path
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
        [ "$1" != tmail-api.service ] || [ ! -e "$FAKE_SYSTEMD_STATE/fail-api" ] || exit 42
        : > "$FAKE_SYSTEMD_STATE/active/$1"
        ;;
    daemon-reload|status) ;;
    *) exit 2 ;;
esac
""")
    command.chmod(0o755)
    return command, state


def _release_tree(tmp_path: Path):
    stage = tmp_path / "stage"
    live = tmp_path / "live"
    systemd = tmp_path / "systemd"
    (stage / "deploy").mkdir(parents=True)
    systemd.mkdir()
    (stage / "version").write_text("new")
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


@pytest.mark.parametrize("name", ["install.sh", "deploy.sh"])
def test_deployment_entrypoints_use_tested_release_helper(name):
    script = (ROOT / "deploy" / name).read_text()
    assert "deploy/release.sh" in script
    assert 'bash "$STAGE_DIR/deploy/release.sh" "$STAGE_DIR" "$REMOTE_DIR"' in script


@pytest.mark.parametrize("name", ["install.sh", "deploy.sh"])
def test_privileged_scripts_do_not_use_predictable_temp_files(name):
    script = (ROOT / "deploy" / name).read_text()
    assert "/tmp/tmail-requirements.txt" not in script
    assert "/tmp/main.cf.dedup" not in script
