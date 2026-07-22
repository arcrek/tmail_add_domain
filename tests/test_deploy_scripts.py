from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize("name", ["install.sh", "deploy.sh"])
def test_release_is_staged_validated_and_promoted_before_restart(name):
    script = (ROOT / "deploy" / name).read_text()
    validate = script.index("python3 -m src.config validate-web")
    promote = script.index('mv "$STAGE_DIR" "$REMOTE_DIR"')
    policy = script.index("systemctl restart tmail-policy", promote)
    api = script.index("systemctl restart tmail-api", policy)

    assert "mktemp -d" in script
    assert "$STAGE_DIR/src" in script
    assert "$STAGE_DIR/frontend/dist" in script
    assert "install -m 600" in script
    assert script.index("pip3 install") < promote
    assert validate < promote < policy < api


@pytest.mark.parametrize("name", ["install.sh", "deploy.sh"])
def test_privileged_scripts_do_not_use_predictable_temp_files(name):
    script = (ROOT / "deploy" / name).read_text()
    assert "/tmp/tmail-requirements.txt" not in script
    assert "/tmp/main.cf.dedup" not in script
    assert "BACKUP_DIR=$(mktemp -d" in script
