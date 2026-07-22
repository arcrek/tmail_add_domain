from types import SimpleNamespace
from unittest.mock import MagicMock

from src import email_janitor


def _config(account_id: str):
    return SimpleNamespace(
        jmap_url="https://mail.example/jmap",
        jmap_token="private-token",
        catchall_address="admin@example.com",
        mail_account_id=account_id,
        retention_days=30,
    )


def _client_context():
    client = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = client
    context.__exit__.return_value = False
    return client, context


def test_janitor_uses_configured_mail_account_id(monkeypatch):
    client, context = _client_context()
    query = MagicMock(return_value=[])
    jmap_class = MagicMock()
    monkeypatch.setattr(email_janitor, "load_config", lambda _path: _config("configured-account"))
    monkeypatch.setattr(email_janitor.httpx, "Client", MagicMock(return_value=context))
    monkeypatch.setattr(email_janitor, "_query_old_emails", query)
    monkeypatch.setattr(email_janitor, "JmapClient", jmap_class)

    email_janitor.run("config.json")

    assert query.call_args.args[2] == "configured-account"
    jmap_class.assert_not_called()


def test_janitor_discovers_the_primary_mail_account_when_not_configured(monkeypatch):
    client, context = _client_context()
    query = MagicMock(return_value=[])
    jmap = MagicMock()
    jmap.discover_mail_account_id.return_value = "primary-account"
    jmap_class = MagicMock(return_value=jmap)
    monkeypatch.setattr(email_janitor, "load_config", lambda _path: _config(""))
    monkeypatch.setattr(email_janitor.httpx, "Client", MagicMock(return_value=context))
    monkeypatch.setattr(email_janitor, "_query_old_emails", query)
    monkeypatch.setattr(email_janitor, "JmapClient", jmap_class)

    email_janitor.run("config.json")

    jmap_class.assert_called_once_with(
        "https://mail.example/jmap", "private-token", "admin@example.com", client=client
    )
    jmap.discover_mail_account_id.assert_called_once_with()
    assert query.call_args.args[2] == "primary-account"
