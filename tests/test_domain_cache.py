from __future__ import annotations
import json
import os
import pytest
from unittest.mock import MagicMock
from src.domain_cache import DomainCache

def test_empty_on_missing_file(tmp_path):
    cache = DomainCache(str(tmp_path / "domains.json"))
    cache.load()
    assert not cache.contains("example.com")

def test_load_existing_file(tmp_path):
    f = tmp_path / "domains.json"
    f.write_text('["example.com", "test.org"]')
    cache = DomainCache(str(f))
    cache.load()
    assert cache.contains("example.com")
    assert cache.contains("test.org")
    assert not cache.contains("other.net")

def test_add_persists_to_disk(tmp_path):
    path = str(tmp_path / "sub" / "domains.json")
    cache = DomainCache(path)
    cache.load()
    cache.add("new.com")
    assert cache.contains("new.com")
    with open(path) as f:
        data = json.load(f)
    assert "new.com" in data

def test_corrupt_file_resets_to_empty(tmp_path):
    f = tmp_path / "domains.json"
    f.write_text("not valid json{{")
    cache = DomainCache(str(f))
    cache.load()
    assert not cache.contains("example.com")

def test_no_tmp_file_left_after_write(tmp_path):
    path = str(tmp_path / "domains.json")
    cache = DomainCache(path)
    cache.load()
    cache.add("a.com")
    assert not os.path.exists(path + ".tmp")

def test_add_many(tmp_path):
    path = str(tmp_path / "domains.json")
    cache = DomainCache(path)
    cache.load()
    cache.add_many(["a.com", "b.com", "c.com"])
    assert cache.contains("a.com")
    assert cache.contains("c.com")


def test_domains_are_sorted_copies_and_replace_persists(tmp_path):
    path = str(tmp_path / "domains.json")
    cache = DomainCache(path)
    cache.load()
    cache.add_many(["b.com", "a.com"])
    domains = cache.domains()
    assert domains == ["a.com", "b.com"]
    domains.append("other.com")
    assert cache.domains() == ["a.com", "b.com"]
    cache.replace(["d.com", "c.com", "c.com"])
    assert cache.domains() == ["c.com", "d.com"]
    with open(path) as f:
        assert json.load(f) == ["c.com", "d.com"]


def test_replace_failure_keeps_memory_and_file(tmp_path, monkeypatch):
    path = tmp_path / "domains.json"
    path.write_text('["old.example"]')
    cache = DomainCache(str(path))
    cache.load()
    monkeypatch.setattr("src.domain_cache.os.replace", MagicMock(side_effect=OSError("disk full")))

    with pytest.raises(OSError, match="disk full"):
        cache.replace(["new.example"])

    assert cache.domains() == ["old.example"]
    assert json.loads(path.read_text()) == ["old.example"]
