from __future__ import annotations
import json
import pytest
from src.config import load_config, Config

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
