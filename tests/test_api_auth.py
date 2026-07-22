import pytest

from src.api_auth import AddressToken, AddressValidationError, active_domains, normalize_address
from src.api_state import StateStore
from src.domain_cache import DomainCache


def test_address_token_round_trip_and_tamper_rejection():
    signer = AddressToken("s" * 32)
    token = signer.issue("User@Example.com")
    assert signer.read(token) == "user@example.com"
    with pytest.raises(ValueError):
        signer.read(token + "x")


def test_normalize_address_applies_whitelist_and_forbidden_ids():
    settings = {"local_part_min": 3, "local_part_max": 32, "forbidden_ids": ["admin"]}
    assert normalize_address("User@Example.com", ["example.com"], settings) == "user@example.com"
    with pytest.raises(AddressValidationError):
        normalize_address("admin@example.com", ["example.com"], settings)
    with pytest.raises(AddressValidationError):
        normalize_address("user@other.com", ["example.com"], settings)


def test_auto_sync_uses_cache_and_off_uses_frozen_domains(tmp_path):
    cache = tmp_path / "domains.json"
    cache.write_text('["live.example"]')
    state = StateStore(str(tmp_path / "state.db"))
    assert active_domains(str(cache), state) == ["live.example"]
    state.replace_frozen_domains(["frozen.example"])
    state.update_settings({"auto_sync_domains": False})
    assert active_domains(str(cache), state) == ["frozen.example"]


def test_auto_sync_reuses_last_valid_long_lived_cache_snapshot(tmp_path):
    path = tmp_path / "domains.json"
    path.write_text('["live.example"]')
    cache = DomainCache(str(path))
    cache.load()
    state = StateStore(str(tmp_path / "state.db"))

    path.write_text("corrupt")

    assert active_domains(cache, state) == ["live.example"]
