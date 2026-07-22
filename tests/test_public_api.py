from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace
import threading
from unittest.mock import MagicMock, call

import pytest
from fastapi.testclient import TestClient

from src import api_server
from src import admin_api
from src.api_server import create_app
from src.jmap_client import _SUMMARY_PROPERTIES


MESSAGE = {
    "id": "m1",
    "blobId": "source-1",
    "threadId": "thread-1",
    "from": [{"name": "Sender", "email": "sender@example.net"}],
    "to": [{"name": "Inbox", "email": "box@example.com"}],
    "cc": [],
    "bcc": [],
    "subject": "Hello",
    "preview": "A short preview",
    "keywords": {},
    "hasAttachment": True,
    "size": 321,
    "receivedAt": "2026-07-22T12:00:00Z",
    "verifications": ["dkim"],
    "retention": True,
    "retentionDate": "2026-08-22T12:00:00Z",
    "bodyValues": {
        "plain": {"value": "Plain body"},
        "markup": {"value": "<p>HTML body</p>"},
    },
    "textBody": [{"partId": "plain"}],
    "htmlBody": [{"partId": "markup"}],
    "attachments": [{
        "blobId": "attachment-1",
        "name": "notes.txt",
        "type": "text/plain",
        "size": 7,
        "disposition": "attachment",
        "transferEncoding": "base64",
        "related": True,
    }],
    "header:Delivered-To:asAddresses": [],
}


@pytest.fixture
def config_path(tmp_path):
    cache = tmp_path / "domains.json"
    cache.write_text('["example.com"]')
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "jmap_url": "https://mail.example/jmap",
        "jmap_token": "private-jmap-token",
        "mx_hostname": "mail.example.com",
        "catchall_address": "admin@example.com",
        "listen_addr": "127.0.0.1",
        "listen_port": 10030,
        "cache_file": str(cache),
        "api_token_secret": "s" * 32,
        "admin_password": "admin-secret",
        "state_db": "state.db",
        "mail_account_id": "mail-account",
    }))
    return path


@pytest.fixture
def fake_jmap():
    fake = MagicMock()
    fake.discover_mail_account_id.return_value = "mail-account"
    fake.list_messages.return_value = (1, [dict(MESSAGE)])
    fake.get_message.return_value = dict(MESSAGE)
    fake.set_seen.return_value = True
    fake.delete_message.return_value = True
    fake.download_blob.side_effect = lambda _account, _blob, _name, content_type: (
        iter([b"pay", b"load"]), content_type
    )
    return fake


@pytest.fixture
def client(config_path, fake_jmap):
    app = create_app(str(config_path))
    app.state.jmap = fake_jmap
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def bearer(client):
    token = client.post("/token", json={"address": "box@example.com"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_domains_are_a_hydra_collection(client):
    response = client.get("/domains")
    assert response.status_code == 200
    body = response.json()
    assert body["@type"] == "hydra:Collection"
    assert body["hydra:member"][0]["domain"] == "example.com"
    assert body["hydra:view"]["@type"] == "hydra:PartialCollectionView"
    assert body["hydra:view"]["hydra:first"] == "/domains?page=1"
    assert body["hydra:search"]["hydra:template"] == "/domains{?page}"
    assert body["hydra:search"]["hydra:mapping"][0]["variable"] == "page"


def test_passwordless_token_and_me(client):
    token_response = client.post("/token", json={"address": "box@example.com"})
    assert token_response.status_code == 200
    token = token_response.json()["token"]
    me = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["address"] == "box@example.com"


def test_accounts_validate_without_persisting(client):
    first = client.post("/accounts", json={"address": "box@example.com"})
    second = client.post("/accounts", json={"address": "BOX@example.com"})
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    with sqlite3.connect(client.app.state.state_store.path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "accounts" not in tables


def test_site_exposes_only_public_settings(client):
    body = client.get("/site").json()
    assert body["appName"] == "Temporary Inbox"
    assert body["fetchSeconds"] == 20
    assert "jmapToken" not in body
    assert "adminPassword" not in body


def test_messages_require_bearer_and_return_hydra(client, bearer):
    assert client.get("/messages").status_code == 401
    response = client.get("/messages", headers=bearer)
    assert response.json()["@id"] == "/messages"


def test_message_pagination_uses_configured_limit(client, bearer, fake_jmap):
    client.app.state.state_store.update_settings({"message_limit": 7})
    fake_jmap.list_messages.return_value = (15, [dict(MESSAGE)])
    response = client.get("/messages?page=3", headers=bearer)
    assert response.status_code == 200
    fake_jmap.list_messages.assert_called_once_with("mail-account", "box@example.com", 7, 14)
    assert response.json()["hydra:view"] == {
        "@id": "/messages?page=3",
        "@type": "hydra:PartialCollectionView",
        "hydra:first": "/messages?page=1",
        "hydra:last": "/messages?page=3",
        "hydra:previous": "/messages?page=2",
    }
    assert response.json()["hydra:search"]["hydra:template"] == "/messages{?page}"


def test_public_mail_request_waits_for_atomic_config_client_publication(
    client, bearer, fake_jmap, monkeypatch
):
    request = SimpleNamespace(app=client.app)
    build_started = threading.Event()
    release_build = threading.Event()
    request_done = threading.Event()
    errors = []
    responses = []
    new_jmap = MagicMock()
    new_jmap.list_messages.return_value = (1, [dict(MESSAGE)])

    def build_client(_url, _token, _catchall):
        build_started.set()
        release_build.wait(2)
        return new_jmap

    monkeypatch.setattr(admin_api, "JmapClient", build_client)

    def publish():
        try:
            admin_api.update_settings(
                request, {"mailServer": {"mailAccountId": "new-account"}}, {}
            )
        except Exception as exc:
            errors.append(exc)

    def load_messages():
        try:
            responses.append(client.get("/messages", headers=bearer))
        except Exception as exc:
            errors.append(exc)
        finally:
            request_done.set()

    publisher = threading.Thread(target=publish)
    reader = threading.Thread(target=load_messages)
    publisher.start()
    assert build_started.wait(1)
    reader.start()
    request_done.wait(0.5)
    release_build.set()
    publisher.join(2)
    reader.join(2)

    assert not errors
    assert not publisher.is_alive() and not reader.is_alive()
    assert responses[0].status_code == 200
    fake_jmap.list_messages.assert_not_called()
    new_jmap.list_messages.assert_called_once_with(
        "new-account", "box@example.com", 15, 0
    )


def test_messages_filter_jmap_overreturn_before_serialization(client, bearer, fake_jmap):
    foreign = dict(MESSAGE, id="foreign-secret", to=[{"email": "other@example.com"}])
    fake_jmap.list_messages.return_value = (2, [dict(MESSAGE), foreign])
    body = client.get("/messages", headers=bearer).json()
    assert [message["id"] for message in body["hydra:member"]] == ["m1"]
    assert body["hydra:totalItems"] == 1
    assert "foreign-secret" not in json.dumps(body)


def test_jmap_summary_projection_contains_local_ownership_fields():
    assert {"to", "cc", "bcc", "header:Delivered-To:asAddresses"} <= set(_SUMMARY_PROPERTIES)


def test_message_detail_builds_bodies_and_attachment_links(client, bearer):
    body = client.get("/messages/m1", headers=bearer).json()
    assert body["text"] == "Plain body"
    assert body["html"] == ["<p>HTML body</p>"]
    assert body["attachments"][0]["downloadUrl"] == "/messages/m1/attachments/attachment-1"
    assert body["attachments"][0]["transferEncoding"] == "base64"
    assert body["attachments"][0]["related"] is True
    assert body["verifications"] == ["dkim"]
    assert body["retention"] is True
    assert body["retentionDate"] == "2026-08-22T12:00:00Z"
    assert body["downloadUrl"] == "/sources/m1"


def test_message_id_cannot_cross_recipient(client, bearer, fake_jmap):
    fake_jmap.get_message.return_value = {
        "id": "m1",
        "to": [{"email": "other@example.com"}],
        "header:Delivered-To:asAddresses": [],
    }
    assert client.get("/messages/m1", headers=bearer).status_code == 404


@pytest.mark.parametrize(("method", "path", "body"), [
    ("patch", "/messages/m1", {"seen": True}),
    ("delete", "/messages/m1", None),
    ("get", "/messages/m1/attachments/attachment-1", None),
    ("get", "/sources/m1", None),
])
def test_message_operations_cannot_cross_recipient(client, bearer, fake_jmap, method, path, body):
    fake_jmap.get_message.return_value = {
        "id": "m1",
        "blobId": "source-1",
        "to": [{"email": "other@example.com"}],
        "attachments": [{"blobId": "attachment-1", "name": "notes.txt"}],
        "header:Delivered-To:asAddresses": [],
    }
    response = getattr(client, method)(path, headers=bearer, json=body) if body else getattr(client, method)(path, headers=bearer)
    assert response.status_code == 404
    fake_jmap.set_seen.assert_not_called()
    fake_jmap.delete_message.assert_not_called()
    fake_jmap.download_blob.assert_not_called()


def test_seen_patch_loads_owner_before_mutating(client, bearer, fake_jmap):
    response = client.patch("/messages/m1", json={"seen": True}, headers=bearer)
    assert response.status_code == 200
    assert response.json() == {"seen": True}
    assert fake_jmap.method_calls.index(call.get_message("mail-account", "m1")) < fake_jmap.method_calls.index(
        call.set_seen("mail-account", "m1", True)
    )


def test_delete_loads_owner_before_mutating(client, bearer, fake_jmap):
    response = client.delete("/messages/m1", headers=bearer)
    assert response.status_code == 204
    assert fake_jmap.method_calls.index(call.get_message("mail-account", "m1")) < fake_jmap.method_calls.index(
        call.delete_message("mail-account", "m1")
    )


def test_attachment_and_source_stream_after_owner_check(client, bearer, fake_jmap):
    attachment = client.get("/messages/m1/attachments/attachment-1", headers=bearer)
    source = client.get("/sources/m1", headers=bearer)
    assert attachment.content == source.content == b"payload"
    assert attachment.headers["content-type"] == "text/plain; charset=utf-8"
    assert source.headers["content-type"] == "message/rfc822"
    assert "notes.txt" in attachment.headers["content-disposition"]
    assert "m1.eml" in source.headers["content-disposition"]
    assert fake_jmap.get_message.call_count == 2
    assert fake_jmap.download_blob.call_args_list == [
        call("mail-account", "attachment-1", "notes.txt", "text/plain"),
        call("mail-account", "source-1", "m1.eml", "message/rfc822"),
    ]


def test_unknown_attachment_is_not_downloaded(client, bearer, fake_jmap):
    assert client.get("/messages/m1/attachments/guessed", headers=bearer).status_code == 404
    fake_jmap.download_blob.assert_not_called()


def test_blocked_sender_domain_is_masked(client, bearer, fake_jmap):
    client.app.state.state_store.update_settings({"blocked_sender_domains": ["example.net"]})
    body = client.get("/messages", headers=bearer).json()
    assert body["hydra:member"][0]["from"] == {"name": "Blocked sender", "address": "blocked@invalid"}
    assert "sender@example.net" not in json.dumps(body)


def test_whitelist_rejection_and_errors_use_hydra(client, fake_jmap):
    rejected = client.post("/token", json={"address": "box@other.example"})
    fake_jmap.get_message.return_value = None
    missing = client.get("/messages/missing", headers={
        "Authorization": f"Bearer {client.post('/token', json={'address': 'box@example.com'}).json()['token']}"
    })
    assert rejected.status_code == 422
    assert rejected.json()["@type"] == "hydra:Error"
    assert missing.status_code == 404
    assert missing.json()["@type"] == "hydra:Error"


def test_request_validation_and_jmap_failure_use_hydra(client, bearer, fake_jmap):
    invalid = client.post("/token", json={})
    fake_jmap.list_messages.side_effect = RuntimeError("private upstream detail")
    failed = client.get("/messages", headers=bearer)
    assert invalid.status_code == 422
    assert invalid.json()["@type"] == "hydra:Error"
    assert failed.status_code == 502
    assert failed.json()["@type"] == "hydra:Error"
    assert "private upstream detail" not in failed.text


def test_token_rejects_oversized_declared_body_before_json_parsing(client):
    response = client.post(
        "/token",
        content=b'{}',
        headers={"content-type": "application/json", "content-length": "9000"},
    )

    assert response.status_code == 413, response.text
    assert response.json()["@type"] == "hydra:Error"


@pytest.mark.parametrize("headers", [
    {"content-type": "application/json", "transfer-encoding": "chunked"},
    {"content-type": "application/json", "content-length": "2"},
])
def test_token_rejects_oversized_stream_with_missing_or_deceptive_length(client, headers):
    payload = b'{"address":"box@example.com","padding":"' + b"x" * 9000 + b'"}'

    response = client.post("/token", content=iter([payload[:4000], payload[4000:]]), headers=headers)

    assert response.status_code == 413, response.text
    assert response.json()["@type"] == "hydra:Error"


def test_security_headers_and_token_rate_limit(client):
    response = client.get("/docs")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-frame-options"] == "DENY"
    assert "cdn.jsdelivr.net" in response.headers["content-security-policy"]
    for _ in range(10):
        assert client.post("/token", json={"address": "box@example.com"}).status_code == 200
    limited = client.post("/token", json={"address": "box@example.com"})
    assert limited.status_code == 429
    assert limited.json()["@type"] == "hydra:Error"
    assert client.post("/admin/login").status_code == 404


def test_redoc_csp_allows_only_generated_redoc_assets(client):
    csp = client.get("/redoc").headers["content-security-policy"]
    assert "script-src 'self' https://cdn.jsdelivr.net" in csp
    assert "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com" in csp
    assert "font-src https://fonts.gstatic.com" in csp
    assert "img-src 'self' https://fastapi.tiangolo.com" in csp
    assert "*" not in csp


def test_admin_login_path_is_rate_limited(client):
    for _ in range(10):
        assert client.post("/admin/login").status_code == 404
    limited = client.post("/admin/login")
    assert limited.status_code == 429
    assert limited.json()["@type"] == "hydra:Error"


def test_fixed_window_prunes_expired_keys_and_separates_paths(monkeypatch):
    monkeypatch.setattr(api_server.time, "monotonic", MagicMock(side_effect=[0, 0, 61]))
    limiter = api_server._FixedWindowLimiter(limit=1, seconds=60)
    assert limiter.allow(("/token", "192.0.2.1"))
    assert limiter.allow(("/admin/login", "192.0.2.1"))
    assert limiter.allow(("/token", "192.0.2.2"))
    assert set(limiter._windows) == {("/token", "192.0.2.2")}


def test_openapi_documents_passwordless_bearer_contract(client):
    schema = client.get("/openapi.json").json()
    assert "/token" in schema["paths"]
    assert "/messages/{message_id}" in schema["paths"]
    assert schema["paths"]["/messages"]["get"]["security"] == [{"HTTPBearer": []}]
    assert "413" in schema["paths"]["/token"]["post"]["responses"]
    assert "429" in schema["paths"]["/token"]["post"]["responses"]
    attachment = schema["paths"]["/messages/{message_id}/attachments/{blob_id}"]["get"]
    assert attachment["responses"]["200"]["content"]["application/octet-stream"]["schema"] == {
        "type": "string", "format": "binary",
    }
    source = schema["paths"]["/sources/{message_id}"]["get"]
    assert source["responses"]["200"]["content"]["message/rfc822"]["schema"] == {
        "type": "string", "format": "binary",
    }
    address_schema = schema["components"]["schemas"]["AddressRequest"]
    assert set(address_schema["properties"]) == {"address"}
    assert "box@example.com" in json.dumps(address_schema)
