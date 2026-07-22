from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src import api_server
from src.api_server import create_app


@pytest.fixture
def frontend_dist(tmp_path):
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text('<div id="app"></div>')
    (assets / "app.js").write_text("console.log('tmail')")
    return dist


@pytest.fixture
def config_path(tmp_path, frontend_dist):
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
        "api_listen_addr": "127.0.0.2",
        "api_listen_port": 8765,
        "api_token_secret": "s" * 32,
        "admin_password": "admin-secret",
        "state_db": str(tmp_path / "state.db"),
        "frontend_dist": str(frontend_dist),
        "mail_account_id": "mail-account",
    }))
    return path


@pytest.fixture
def client(config_path):
    with TestClient(create_app(str(config_path)), raise_server_exceptions=False) as test_client:
        yield test_client


def test_spa_serves_home_admin_and_address_routes(client, frontend_dist):
    for path in [
        "/",
        "/admin",
        "/box@example.com",
        "/box@disabled.example",
        "/bad..local@example.com",
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert '<div id="app"></div>' in response.text


def test_api_and_docs_are_not_shadowed_by_spa(client):
    assert client.get("/domains").headers["content-type"].startswith("application/ld+json")
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    assert client.get("/openapi.json").status_code == 200
    mismatch = client.get("/token")
    assert mismatch.status_code == 405
    assert '<div id="app"></div>' not in mismatch.text
    assert client.get("/admin/api/settings").status_code == 401
    assert '<div id="app"></div>' not in client.get("/not-an-address").text
    assert client.get("/box@other.example").status_code == 200


def test_assets_are_served_with_immutable_cache(client):
    response = client.get("/assets/app.js")
    assert response.status_code == 200
    assert response.text == "console.log('tmail')"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_missing_frontend_returns_plain_503(config_path, frontend_dist):
    (frontend_dist / "index.html").unlink()
    with TestClient(create_app(str(config_path)), raise_server_exceptions=False) as test_client:
        response = test_client.get("/")
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "Frontend is not installed\n"


def test_main_uses_environment_config_and_api_bind(config_path, monkeypatch):
    called = {}
    monkeypatch.setenv("TMAIL_CONFIG", str(config_path))
    monkeypatch.setattr(api_server.uvicorn, "run", lambda app, host, port: called.update(
        app=app, host=host, port=port
    ))

    api_server.main()

    assert called["host"] == "127.0.0.2"
    assert called["port"] == 8765
    assert called["app"].state.config_store.path == str(config_path)


@pytest.mark.parametrize(("secret", "password", "field"), [
    ("replace-with-32-or-more-random-characters", "admin-secret", "api_token_secret"),
    (" " + "s" * 31 + " ", "admin-secret", "api_token_secret"),
    ("s" * 32, "   ", "admin_password"),
    ("s" * 32, "replace-with-a-strong-admin-password", "admin_password"),
])
def test_api_startup_rejects_weak_or_placeholder_credentials(
    config_path, secret, password, field
):
    config = json.loads(config_path.read_text())
    config.update(api_token_secret=secret, admin_password=password)
    config_path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match=field):
        create_app(str(config_path))
