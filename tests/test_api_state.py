from datetime import datetime, timedelta, timezone

from src.api_state import StateStore


def test_settings_and_frozen_domains_round_trip(tmp_path):
    store = StateStore(str(tmp_path / "state.db"))
    store.update_settings({"auto_sync_domains": False, "fetch_seconds": 20})
    store.replace_frozen_domains(["b.example", "a.example"])
    assert store.get_settings()["auto_sync_domains"] is False
    assert store.get_frozen_domains() == ["a.example", "b.example"]


def test_admin_session_expires(tmp_path):
    store = StateStore(str(tmp_path / "state.db"))
    now = datetime.now(timezone.utc)
    store.create_admin_session("hash", "csrf", now - timedelta(seconds=1))
    assert store.get_admin_session("hash", now) is None


def test_activity_summary_counts_domains(tmp_path):
    store = StateStore(str(tmp_path / "state.db"))
    store.record_event("domain_provisioned", "example.com")
    summary = store.activity_summary()
    assert summary["domainsToday"] == 1
    assert summary["recentDomains"][0]["domain"] == "example.com"
