from __future__ import annotations
import json
import multiprocessing
import os
import pytest
from unittest.mock import MagicMock
from src.domain_cache import DomainCache


def _add_after_stale_load(path, ready, proceed):
    cache = DomainCache(path)
    cache.load()
    ready.set()
    if not proceed.wait(5):
        raise RuntimeError("parent did not release cache writer")
    cache.add("new.example")

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


def test_missing_or_corrupt_reload_retains_last_valid_snapshot(tmp_path):
    path = tmp_path / "domains.json"
    path.write_text('["last-valid.example"]')
    cache = DomainCache(str(path))
    cache.load()

    path.unlink()
    cache.load()
    assert cache.domains() == ["last-valid.example"]

    path.write_text("not json")
    cache.load()
    assert cache.domains() == ["last-valid.example"]

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


def test_stale_process_add_reloads_before_merge_without_resurrecting(tmp_path):
    path = tmp_path / "domains.json"
    path.write_text('["old.example"]')
    context = multiprocessing.get_context("fork")
    ready = context.Event()
    proceed = context.Event()
    process = context.Process(target=_add_after_stale_load, args=(str(path), ready, proceed))
    process.start()
    try:
        assert ready.wait(2)
        authoritative = DomainCache(str(path))
        authoritative.load()
        authoritative.replace(["authoritative.example"])
        proceed.set()
        process.join(5)
        assert process.exitcode == 0
        assert json.loads(path.read_text()) == ["authoritative.example", "new.example"]
    finally:
        proceed.set()
        process.join(5)
        if process.is_alive():
            process.terminate()
            process.join(5)


def test_authoritative_replace_rejects_a_changed_generation(tmp_path):
    path = tmp_path / "domains.json"
    path.write_text('["old.example"]')
    replacement = DomainCache(str(path))
    replacement.load()
    generation = replacement.generation()

    policy = DomainCache(str(path))
    policy.load()
    policy.add("provisioned.example")

    assert replacement.replace(["authoritative.example"], expected_generation=generation) is False
    assert replacement.domains() == ["old.example", "provisioned.example"]
    assert json.loads(path.read_text()) == ["old.example", "provisioned.example"]
