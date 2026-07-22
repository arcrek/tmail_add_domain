from __future__ import annotations
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import pytest
from src import config as config_module
from src.config import Config, ConfigStore, load_config


ROOT = Path(__file__).parents[1]


def _config_data(tmp_path: Path) -> dict[str, object]:
    return {
        "jmap_url": "https://old.example/jmap/",
        "jmap_token": "old",
        "mx_hostname": "mail.example.com",
        "catchall_address": "admin@example.com",
        "listen_addr": "127.0.0.1",
        "listen_port": 10030,
        "cache_file": str(tmp_path / "domains.json"),
        "api_token_secret": "a" * 32,
        "admin_password": "secret",
    }


def _record_fsyncs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    events: list[str] = []
    real_fsync = config_module.os.fsync

    def record(fd: int) -> None:
        events.append("directory" if stat.S_ISDIR(config_module.os.fstat(fd).st_mode) else "file")
        real_fsync(fd)

    monkeypatch.setattr(config_module.os, "fsync", record)
    return events


def _web_config(secret: str, password: str) -> Config:
    return Config(
        jmap_url="https://example.com/jmap/",
        jmap_token="token",
        mx_hostname="mail.example.com",
        catchall_address="admin@example.com",
        listen_addr="127.0.0.1",
        listen_port=10030,
        cache_file="/tmp/domains.json",
        api_token_secret=secret,
        admin_password=password,
    )

def test_load_valid_config(tmp_path):
    data = {
        "jmap_url": "https://example.com/jmap/",
        "jmap_token": "tok123",
        "mx_hostname": "mail.example.com",
        "catchall_address": "admin@example.com",
        "listen_addr": "127.0.0.1",
        "listen_port": 10030,
        "cache_file": "/tmp/domains.json",
    }
    f = tmp_path / "config.json"
    f.write_text(json.dumps(data))
    cfg = load_config(str(f))
    assert isinstance(cfg, Config)
    assert cfg.jmap_token == "tok123"
    assert cfg.listen_port == 10030

def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/config.json")


def test_frontend_defaults_are_loaded(tmp_path):
    data = {
        "jmap_url": "https://example.com/jmap/",
        "jmap_token": "tok",
        "mx_hostname": "mail.example.com",
        "catchall_address": "admin@example.com",
        "listen_addr": "127.0.0.1",
        "listen_port": 10030,
        "cache_file": str(tmp_path / "domains.json"),
        "api_token_secret": "a" * 32,
        "admin_password": "secret",
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data))
    cfg = load_config(str(path))
    assert cfg.api_listen_addr == "127.0.0.1"
    assert cfg.api_listen_port == 8000
    assert cfg.state_db.endswith("state.db")
    assert cfg.frontend_dist.endswith("frontend/dist")


def test_legacy_policy_config_still_loads_without_web_secrets(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "jmap_url": "https://example.com/jmap/",
        "jmap_token": "tok",
        "mx_hostname": "mail.example.com",
        "catchall_address": "admin@example.com",
        "listen_addr": "127.0.0.1",
        "listen_port": 10030,
        "cache_file": str(tmp_path / "domains.json"),
    }))
    cfg = load_config(str(path))
    assert cfg.api_token_secret == ""
    assert cfg.admin_password == ""


def test_config_store_atomically_updates_allowed_fields(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "jmap_url": "https://old.example/jmap/",
        "jmap_token": "old",
        "mx_hostname": "mail.example.com",
        "catchall_address": "admin@example.com",
        "listen_addr": "127.0.0.1",
        "listen_port": 10030,
        "cache_file": str(tmp_path / "domains.json"),
        "api_token_secret": "a" * 32,
        "admin_password": "secret",
    }))
    store = ConfigStore(str(path))
    cfg = store.update({"jmap_url": "https://new.example/jmap/"})
    assert cfg.jmap_url == "https://new.example/jmap/"
    assert not (tmp_path / "config.json.tmp").exists()


def test_config_store_update_preserves_config_mode(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "jmap_url": "https://old.example/jmap/",
        "jmap_token": "old",
        "mx_hostname": "mail.example.com",
        "catchall_address": "admin@example.com",
        "listen_addr": "127.0.0.1",
        "listen_port": 10030,
        "cache_file": str(tmp_path / "domains.json"),
    }))
    path.chmod(0o600)
    ConfigStore(str(path)).update({"jmap_url": "https://new.example/jmap/"})
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_config_store_updates_in_service_owned_runtime_directory(tmp_path):
    release = tmp_path / "release"
    release.mkdir(mode=0o755)
    (release / "src").mkdir()
    release.chmod(0o555)
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    path = runtime / "config.json"
    path.write_text(json.dumps({
        "jmap_url": "https://old.example/jmap/",
        "jmap_token": "old",
        "mx_hostname": "mail.example.com",
        "catchall_address": "admin@example.com",
        "listen_addr": "127.0.0.1",
        "listen_port": 10030,
        "cache_file": str(runtime / "domains.json"),
    }))
    path.chmod(0o600)

    ConfigStore(str(path)).update({"jmap_url": "https://new.example/jmap/"})

    assert load_config(str(path)).jmap_url == "https://new.example/jmap/"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not (runtime / "config.json.tmp").exists()
    assert stat.S_IMODE(release.stat().st_mode) == 0o555


def test_install_runtime_config_creates_mode_0600_file(tmp_path):
    target = tmp_path / "runtime" / "config.json"
    target.parent.mkdir(mode=0o700)
    payload = '{"jmap_url": "https://example.com/jmap/"}\n'

    result = subprocess.run(
        [sys.executable, str(ROOT / "src" / "config.py"), "install-runtime", str(target)],
        input=payload,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert target.read_text() == payload
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    installed = target.stat()
    assert result.stdout == f"{installed.st_dev}:{installed.st_ino}\n"


def test_install_runtime_config_does_not_follow_existing_symlink(tmp_path):
    target = tmp_path / "runtime" / "config.json"
    target.parent.mkdir(mode=0o700)
    victim = tmp_path / "victim"
    victim.write_text("untouched")
    target.symlink_to(victim)

    result = subprocess.run(
        [sys.executable, str(ROOT / "src" / "config.py"), "install-runtime", str(target)],
        input="replacement",
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "File exists" in result.stderr
    assert target.is_symlink()
    assert victim.read_text() == "untouched"


def test_install_runtime_config_fsyncs_file_then_parent(tmp_path, monkeypatch):
    target = tmp_path / "runtime" / "config.json"
    target.parent.mkdir(mode=0o700)
    monkeypatch.setattr(config_module.sys, "stdin", io.StringIO("config"))
    events = _record_fsyncs(monkeypatch)

    config_module._install_runtime_config(str(target))

    assert events == ["file", "directory"]


def test_install_runtime_config_does_not_acknowledge_directory_fsync_failure(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "runtime" / "config.json"
    target.parent.mkdir(mode=0o700)
    monkeypatch.setattr(config_module.sys, "stdin", io.StringIO("config"))
    events: list[str] = []
    real_fsync = config_module.os.fsync

    def fail_directory(fd: int) -> None:
        if stat.S_ISDIR(config_module.os.fstat(fd).st_mode):
            events.append("directory")
            raise OSError("directory fsync failed")
        events.append("file")
        real_fsync(fd)

    monkeypatch.setattr(config_module.os, "fsync", fail_directory)

    with pytest.raises(OSError, match="directory fsync failed"):
        config_module._install_runtime_config(str(target))

    assert not target.exists()
    assert events == ["file", "directory", "directory"]


def test_remove_runtime_config_removes_exact_inode_and_fsyncs_parent(tmp_path, monkeypatch):
    target = tmp_path / "runtime" / "config.json"
    target.parent.mkdir(mode=0o700)
    target.write_text("created by deployment")
    installed = target.stat()
    events = _record_fsyncs(monkeypatch)

    config_module._remove_runtime_config(
        str(target),
        (installed.st_dev, installed.st_ino),
    )

    assert not target.exists()
    assert events == ["directory"]


def test_remove_runtime_config_preserves_atomic_replacement(tmp_path):
    target = tmp_path / "runtime" / "config.json"
    target.parent.mkdir(mode=0o700)
    target.write_text("created by deployment")
    installed = target.stat()
    replacement = target.with_suffix(".replacement")
    replacement.write_text("concurrent replacement")
    replacement.replace(target)

    with pytest.raises(ValueError, match="identity changed"):
        config_module._remove_runtime_config(
            str(target),
            (installed.st_dev, installed.st_ino),
        )

    assert target.read_text() == "concurrent replacement"


def test_remove_runtime_config_does_not_follow_symlink(tmp_path):
    target = tmp_path / "runtime" / "config.json"
    target.parent.mkdir(mode=0o700)
    victim = tmp_path / "victim"
    victim.write_text("untouched")
    installed = victim.stat()
    target.symlink_to(victim)

    with pytest.raises(ValueError, match="not a regular file"):
        config_module._remove_runtime_config(
            str(target),
            (installed.st_dev, installed.st_ino),
        )

    assert target.is_symlink()
    assert victim.read_text() == "untouched"


def test_remove_runtime_config_rejects_directory(tmp_path):
    target = tmp_path / "runtime" / "config.json"
    target.mkdir(parents=True)
    installed = target.stat()

    with pytest.raises(ValueError, match="not a regular file"):
        config_module._remove_runtime_config(
            str(target),
            (installed.st_dev, installed.st_ino),
        )

    assert target.is_dir()


def test_remove_runtime_config_cli_removes_matching_inode(tmp_path):
    target = tmp_path / "runtime" / "config.json"
    target.parent.mkdir(mode=0o700)
    target.write_text("created by deployment")
    installed = target.stat()

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "src" / "config.py"),
            "remove-runtime",
            str(target),
            f"{installed.st_dev}:{installed.st_ino}",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert not target.exists()


def test_remove_runtime_config_cli_reports_directory_fsync_failure(
    tmp_path,
    monkeypatch,
    capsys,
):
    target = tmp_path / "runtime" / "config.json"
    target.parent.mkdir(mode=0o700)
    target.write_text("created by deployment")
    installed = target.stat()

    def fail_directory(_fd: int) -> None:
        raise OSError("directory fsync failed")

    monkeypatch.setattr(config_module.os, "fsync", fail_directory)

    result = config_module._main([
        "remove-runtime",
        str(target),
        f"{installed.st_dev}:{installed.st_ino}",
    ])

    assert result == 1
    assert "directory fsync failed" in capsys.readouterr().err
    assert not target.exists()


def test_config_store_fsyncs_file_then_parent(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(_config_data(tmp_path)))
    store = ConfigStore(str(path))
    events = _record_fsyncs(monkeypatch)

    store.update({"jmap_url": "https://new.example/jmap/"})

    assert events == ["file", "directory"]


def test_config_store_does_not_acknowledge_directory_fsync_failure(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(_config_data(tmp_path)))
    store = ConfigStore(str(path))
    real_fsync = config_module.os.fsync

    def fail_directory(fd: int) -> None:
        if stat.S_ISDIR(config_module.os.fstat(fd).st_mode):
            raise OSError("directory fsync failed")
        real_fsync(fd)

    monkeypatch.setattr(config_module.os, "fsync", fail_directory)

    with pytest.raises(OSError, match="directory fsync failed"):
        store.update({"jmap_url": "https://new.example/jmap/"})

    assert store._config.jmap_url == "https://old.example/jmap/"
    assert not list(tmp_path.glob(".config.json.*.tmp"))


def test_config_store_cleans_unique_temp_when_replace_fails(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(_config_data(tmp_path)))
    store = ConfigStore(str(path))

    def fail_replace(source: str, destination: str) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(config_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        store.update({"jmap_url": "https://new.example/jmap/"})

    assert {item.name for item in tmp_path.iterdir()} == {"config.json"}


def test_config_store_ignores_predictable_temp_symlink(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(_config_data(tmp_path)))
    victim = tmp_path / "victim"
    victim.write_text("untouched")
    predictable = tmp_path / "config.json.tmp"
    predictable.symlink_to(victim)

    ConfigStore(str(path)).update({"jmap_url": "https://new.example/jmap/"})

    assert victim.read_text() == "untouched"
    assert predictable.is_symlink()
    assert load_config(str(path)).jmap_url == "https://new.example/jmap/"


@pytest.mark.parametrize(("secret", "password", "field"), [
    (" " + "a" * 31 + " ", "secret", "api_token_secret"),
    ("replace-with-my-real-random-string", "secret", "api_token_secret"),
    ("a" * 32, "   ", "admin_password"),
    ("a" * 32, "replace-with-a-strong-admin-password", "admin_password"),
])
def test_web_config_rejects_weak_or_placeholder_credentials(secret, password, field):
    with pytest.raises(ValueError, match=field) as exc:
        config_module.validate_web_config(_web_config(secret, password))
    if field == "api_token_secret":
        assert "python3 -c 'import secrets; print(secrets.token_urlsafe(32))'" in str(exc.value)


def test_web_config_accepts_32_stripped_token_characters():
    config = _web_config(" " + "a" * 32 + " ", "secret")
    assert config_module.validate_web_config(config) is config
