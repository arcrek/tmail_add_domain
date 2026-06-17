from __future__ import annotations
import json
import os
import pytest
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
