from __future__ import annotations
import json
import stat
import pytest
from src.config import Config, ConfigStore, load_config

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
