from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api_server import create_app


@pytest.fixture
def cache_file(tmp_path):
    path = tmp_path / "domains.json"
    path.write_text('["old.example"]')
    return path


@pytest.fixture
def config_path(tmp_path, cache_file):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "jmap_url": "https://mail.example/jmap",
        "jmap_token": "private-jmap-token",
        "mx_hostname": "mail.example.com",
        "catchall_address": "admin@example.com",
        "listen_addr": "127.0.0.1",
        "listen_port": 10030,
        "cache_file": str(cache_file),
        "api_token_secret": "s" * 32,
        "admin_password": "admin-secret",
        "state_db": "state.db",
        "mail_account_id": "mail-account",
    }))
    return path


@pytest.fixture
def fake_jmap():
    fake = MagicMock()
    fake.list_domains.return_value = ["old.example"]
    fake.message_counts.return_value = {"stored": 12, "today": 3, "sevenDays": 8}
    fake.discover_mail_account_id.return_value = "mail-account"
    return fake


@pytest.fixture
def client(config_path, fake_jmap):
    app = create_app(str(config_path))
    app.state.jmap = fake_jmap
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def admin_client(client):
    response = client.post("/admin/api/login", json={"password": "admin-secret"})
    assert response.status_code == 200
    client.csrf = {"X-CSRF-Token": response.json()["csrfToken"]}
    return client


def test_admin_login_sets_http_only_cookie(client):
    response = client.post("/admin/api/login", json={"password": "admin-secret"})
    assert response.status_code == 200
    assert response.json()["csrfToken"]
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie


def test_wrong_password_is_rejected(client):
    response = client.post("/admin/api/login", json={"password": "wrong"})
    assert response.status_code == 401
    assert "tmail_admin" not in response.cookies


def test_expired_session_is_rejected(admin_client):
    token = admin_client.cookies.get("tmail_admin")
    admin_client.app.state.state_store.create_admin_session(
        hashlib.sha256(token.encode()).hexdigest(),
        admin_client.csrf["X-CSRF-Token"],
        datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    assert admin_client.get("/admin/api/settings").status_code == 401


def test_logout_deletes_session_and_cookie(admin_client):
    response = admin_client.post("/admin/api/logout", headers=admin_client.csrf)
    assert response.status_code == 204
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert admin_client.get("/admin/api/settings").status_code == 401


def test_settings_mask_secret_and_require_csrf(admin_client):
    response = admin_client.get("/admin/api/settings")
    assert response.json()["mailServer"]["jmapToken"] == "********"
    assert admin_client.put("/admin/api/settings", json={}).status_code == 403


def test_csrf_mismatch_is_rejected(admin_client):
    response = admin_client.post(
        "/admin/api/sync-domains", headers={"X-CSRF-Token": "wrong"}
    )
    assert response.status_code == 403


@pytest.mark.parametrize("site", [
    {"fetchSeconds": 9},
    {"fetchSeconds": 301},
    {"messageLimit": 0},
    {"messageLimit": 101},
    {"localPartMin": 0},
    {"localPartMax": 65},
    {"localPartMin": 20, "localPartMax": 10},
    {"primaryColor": "red"},
    {"logoDataUrl": "data:text/plain;base64,SGVsbG8="},
])
def test_setting_bounds_are_rejected(admin_client, site):
    response = admin_client.put(
        "/admin/api/settings", json={"site": site}, headers=admin_client.csrf
    )
    assert response.status_code == 422


def test_list_settings_are_normalized_and_unique(admin_client):
    response = admin_client.put("/admin/api/settings", json={"site": {
        "forbiddenIds": [" Admin ", "admin", "Root"],
        "blockedSenderDomains": [" EXAMPLE.COM ", "example.com", "Täst.example"],
    }}, headers=admin_client.csrf)
    assert response.status_code == 200
    site = admin_client.get("/admin/api/settings").json()["site"]
    assert site["forbiddenIds"] == ["admin", "root"]
    assert site["blockedSenderDomains"] == ["example.com", "xn--tst-qla.example"]


def test_masked_or_empty_secret_preserves_current_token(admin_client, config_path, monkeypatch):
    client_class = MagicMock()
    monkeypatch.setattr("src.admin_api.JmapClient", client_class)
    for submitted in ("********", ""):
        response = admin_client.put("/admin/api/settings", json={"mailServer": {
            "jmapUrl": "https://new.example/jmap",
            "jmapToken": submitted,
        }}, headers=admin_client.csrf)
        assert response.status_code == 200
        assert json.loads(config_path.read_text())["jmap_token"] == "private-jmap-token"
    client_class.assert_called_with(
        "https://new.example/jmap", "private-jmap-token", "admin@example.com"
    )


def test_html_ad_setting_round_trip(admin_client):
    values = {
        "headerHtml": "<strong>Header</strong>",
        "footerHtml": "<small>Footer</small>",
        "contentCss": ".notice { color: red; }",
        "adSlots": {"sidebar": "<script>ad()</script>"},
    }
    response = admin_client.put(
        "/admin/api/settings", json={"site": values}, headers=admin_client.csrf
    )
    assert response.status_code == 200
    site = admin_client.get("/admin/api/settings").json()["site"]
    assert {key: site[key] for key in values} == values


def test_disabling_sync_freezes_current_whitelist(admin_client):
    response = admin_client.put("/admin/api/settings", json={"site": {
        "autoSyncDomains": False,
    }}, headers=admin_client.csrf)
    assert response.status_code == 200
    assert admin_client.app.state.state_store.get_frozen_domains() == ["old.example"]


def test_disabling_sync_freezes_latest_policy_cache(admin_client, cache_file):
    cache_file.write_text('["policy-added.example"]')
    response = admin_client.put("/admin/api/settings", json={"site": {
        "autoSyncDomains": False,
    }}, headers=admin_client.csrf)
    assert response.status_code == 200
    assert admin_client.app.state.state_store.get_frozen_domains() == ["policy-added.example"]


def test_sync_now_replaces_cache_only_on_success(admin_client, fake_jmap, cache_file):
    fake_jmap.list_domains.return_value = ["new.example"]
    response = admin_client.post("/admin/api/sync-domains", headers=admin_client.csrf)
    assert response.status_code == 200
    assert json.loads(cache_file.read_text()) == ["new.example"]


def test_sync_updates_frozen_snapshot_when_auto_sync_is_off(admin_client, fake_jmap):
    admin_client.put("/admin/api/settings", json={"site": {
        "autoSyncDomains": False,
    }}, headers=admin_client.csrf)
    fake_jmap.list_domains.return_value = ["new.example"]
    assert admin_client.post("/admin/api/sync-domains", headers=admin_client.csrf).status_code == 200
    assert admin_client.app.state.state_store.get_frozen_domains() == ["new.example"]


@pytest.mark.parametrize("result", [[], None])
def test_failed_sync_keeps_working_cache(admin_client, fake_jmap, cache_file, result):
    fake_jmap.list_domains.return_value = result
    response = admin_client.post("/admin/api/sync-domains", headers=admin_client.csrf)
    assert response.status_code == 502
    assert json.loads(cache_file.read_text()) == ["old.example"]
    assert admin_client.app.state.state_store.last_sync()["success"] is False


def test_failed_jmap_test_returns_bad_gateway(admin_client, fake_jmap):
    fake_jmap.message_counts.side_effect = RuntimeError("unavailable")
    response = admin_client.post("/admin/api/test-mail", headers=admin_client.csrf)
    assert response.status_code == 502
    assert "unavailable" not in response.text


def test_dashboard_combines_jmap_and_activity(admin_client, fake_jmap):
    fake_jmap.message_counts.return_value = {"stored": 12, "today": 3, "sevenDays": 8}
    body = admin_client.get("/admin/api/dashboard").json()
    assert body["messages"]["today"] == 3
    assert "domainsToday" in body["domains"]
    assert body["domains"]["active"] == 1
