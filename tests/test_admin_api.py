from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from types import SimpleNamespace
import threading
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
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as test_client:
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
    assert "Secure" in cookie


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


@pytest.mark.parametrize("mail", [
    {"jmapUrl": "https:///missing-host"},
    {"jmapUrl": "http://"},
    {"jmapUrl": "https://bad host/jmap"},
    {"jmapUrl": "https://example.com:notaport/jmap"},
    {"jmapUrl": "https://example.com:99999/jmap"},
    {"jmapUrl": "https://example.com/\x01jmap"},
    {"catchallAddress": "bad@@example.com"},
])
def test_malformed_mail_settings_are_rejected(admin_client, mail):
    response = admin_client.put(
        "/admin/api/settings", json={"mailServer": mail}, headers=admin_client.csrf
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


def test_sync_persistence_failure_keeps_cache_and_records_failure(
    admin_client, fake_jmap, cache_file, monkeypatch
):
    fake_jmap.list_domains.return_value = ["new.example"]
    monkeypatch.setattr(
        "src.domain_cache.os.replace", MagicMock(side_effect=OSError("disk full"))
    )
    response = admin_client.post("/admin/api/sync-domains", headers=admin_client.csrf)
    assert response.status_code == 502
    assert admin_client.app.state.domain_cache.domains() == ["old.example"]
    assert json.loads(cache_file.read_text()) == ["old.example"]
    assert admin_client.app.state.state_store.last_sync()["success"] is False


def test_sync_rejects_domains_from_superseded_jmap(
    admin_client, fake_jmap, cache_file, monkeypatch
):
    from src import admin_api

    request = SimpleNamespace(app=admin_client.app)
    response_started = threading.Event()
    release_response = threading.Event()
    sync_status = []

    def delayed_domains():
        response_started.set()
        release_response.wait(2)
        return ["stale.example"]

    fake_jmap.list_domains.side_effect = delayed_domains
    replacement = MagicMock()
    monkeypatch.setattr(admin_api, "JmapClient", MagicMock(return_value=replacement))

    def sync():
        try:
            admin_api.sync_domains(request, {})
            sync_status.append(200)
        except Exception as exc:
            sync_status.append(getattr(exc, "status_code", None))

    thread = threading.Thread(target=sync)
    thread.start()
    assert response_started.wait(1)
    admin_api.update_settings(
        request, {"mailServer": {"jmapUrl": "https://new.example/jmap"}}, {}
    )
    release_response.set()
    thread.join(2)

    assert not thread.is_alive()
    assert sync_status == [502]
    assert admin_client.app.state.jmap is replacement
    assert admin_client.app.state.domain_cache.domains() == ["old.example"]
    assert json.loads(cache_file.read_text()) == ["old.example"]
    assert admin_client.app.state.state_store.last_sync()["success"] is False


def test_disable_and_sync_commit_in_one_order(admin_client, fake_jmap, monkeypatch):
    from src import admin_api

    request = SimpleNamespace(app=admin_client.app)
    snapshot_read = threading.Event()
    release_disable = threading.Event()
    sync_done = threading.Event()
    errors = []
    real_active_domains = admin_api._active_domains

    def paused_active_domains(request, settings=None):
        domains = real_active_domains(request, settings)
        if settings and settings["auto_sync_domains"]:
            snapshot_read.set()
            release_disable.wait(2)
        return domains

    monkeypatch.setattr(admin_api, "_active_domains", paused_active_domains)
    fake_jmap.list_domains.return_value = ["new.example"]

    def disable():
        try:
            admin_api.update_settings(request, {"site": {"autoSyncDomains": False}}, {})
        except Exception as exc:
            errors.append(exc)

    def sync():
        try:
            admin_api.sync_domains(request, {})
        except Exception as exc:
            errors.append(exc)
        finally:
            sync_done.set()

    disable_thread = threading.Thread(target=disable)
    sync_thread = threading.Thread(target=sync)
    disable_thread.start()
    assert snapshot_read.wait(1)
    sync_thread.start()
    sync_done.wait(0.5)
    release_disable.set()
    disable_thread.join(2)
    sync_thread.join(2)

    assert not errors
    assert not disable_thread.is_alive() and not sync_thread.is_alive()
    assert admin_client.app.state.state_store.get_frozen_domains() == ["new.example"]


def test_newer_mail_config_cannot_leave_older_client_installed(
    admin_client, monkeypatch
):
    from src import admin_api

    request = SimpleNamespace(app=admin_client.app)
    older_build_started = threading.Event()
    release_older_build = threading.Event()
    newer_done = threading.Event()
    errors = []

    def client(url, _token, _catchall):
        value = SimpleNamespace(url=url)
        if "older" in url:
            older_build_started.set()
            release_older_build.wait(2)
        return value

    monkeypatch.setattr(admin_api, "JmapClient", client)

    def update(url, done=None):
        try:
            admin_api.update_settings(
                request, {"mailServer": {"jmapUrl": url}}, {}
            )
        except Exception as exc:
            errors.append(exc)
        finally:
            if done:
                done.set()

    older = threading.Thread(target=update, args=("https://older.example/jmap",))
    newer = threading.Thread(
        target=update, args=("https://newer.example/jmap", newer_done)
    )
    older.start()
    assert older_build_started.wait(1)
    newer.start()
    newer_done.wait(0.5)
    release_older_build.set()
    older.join(2)
    newer.join(2)

    assert not errors
    assert not older.is_alive() and not newer.is_alive()
    assert admin_client.app.state.config_store.get().jmap_url == "https://newer.example/jmap"
    assert admin_client.app.state.jmap.url == "https://newer.example/jmap"


def test_test_mail_uses_one_jmap_snapshot(admin_client, fake_jmap):
    replacement = MagicMock()
    replacement.message_counts.return_value = {"stored": 99, "today": 99, "sevenDays": 99}

    def swap_client():
        admin_client.app.state.jmap = replacement
        return ["old.example"]

    fake_jmap.list_domains.side_effect = swap_client
    response = admin_client.post("/admin/api/test-mail", headers=admin_client.csrf)
    assert response.status_code == 200
    fake_jmap.message_counts.assert_called_once_with("mail-account")
    replacement.message_counts.assert_not_called()


def test_dashboard_uses_one_jmap_snapshot(admin_client, fake_jmap, monkeypatch):
    replacement = MagicMock()
    replacement.message_counts.return_value = {"stored": 99, "today": 99, "sevenDays": 99}
    state = admin_client.app.state.state_store
    real_get_settings = state.get_settings

    def swap_client():
        settings = real_get_settings()
        admin_client.app.state.jmap = replacement
        return settings

    monkeypatch.setattr(state, "get_settings", swap_client)
    response = admin_client.get("/admin/api/dashboard")
    assert response.status_code == 200
    fake_jmap.message_counts.assert_called_once_with("mail-account")
    replacement.message_counts.assert_not_called()


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
    assert "domainsSevenDays" in body["domains"]
    assert body["domains"]["active"] == 1


def test_settings_and_dashboard_keep_success_and_error_sync_history(admin_client):
    state = admin_client.app.state.state_store
    state.record_sync(True, "1 domain")
    state.record_sync(False, "TimeoutError")

    settings = admin_client.get("/admin/api/settings").json()
    dashboard = admin_client.get("/admin/api/dashboard").json()

    for body in (settings, dashboard):
        assert body["lastSync"]["success"] is False
        assert body["lastSuccessfulSync"]["detail"] == "1 domain"
        assert body["lastSyncError"]["detail"] == "TimeoutError"
