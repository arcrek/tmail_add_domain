from __future__ import annotations
import io
from types import SimpleNamespace
import threading
import pytest
from unittest.mock import MagicMock, patch
import src.policy_daemon as pd

def _handler(lines: list) -> pd.PolicyHandler:
    h = pd.PolicyHandler.__new__(pd.PolicyHandler)
    h.rfile = io.BytesIO(("\n".join(lines) + "\n\n").encode())
    h.wfile = io.BytesIO()
    return h

def _setup(known: set = None, jmap_ok: bool = True):
    pd._config = MagicMock(
        mx_hostname="mail.tm-mails.com",
        jmap_url="https://mail.example/jmap",
        jmap_token="token",
        catchall_address="admin@example.com",
    )
    pd._config_store = MagicMock()
    pd._config_store.get.return_value = pd._config
    cache = MagicMock()
    cache.contains.side_effect = lambda d: d in (known or set())
    pd._cache = cache
    pd._state = MagicMock()
    jmap = MagicMock()
    jmap.provision_domain.return_value = jmap_ok
    pd._jmap = jmap
    pd._jmap_fingerprint = (
        pd._config.jmap_url, pd._config.jmap_token, pd._config.catchall_address,
    )
    return cache, jmap, pd._state

def test_known_domain_returns_ok():
    cache, jmap, _state = _setup(known={"example.com"})
    h = _handler(["recipient=user@example.com"])
    h.handle()
    assert h.wfile.getvalue() == b"action=OK\n\n"
    jmap.provision_domain.assert_not_called()

def test_unknown_mx_match_provisions_records_and_returns_ok():
    cache, jmap, state = _setup()
    h = _handler(["recipient=user@newdomain.com"])
    with patch("src.policy_daemon.mx_matches", return_value=True):
        h.handle()
    assert h.wfile.getvalue() == b"action=OK\n\n"
    jmap.provision_domain.assert_called_once_with("newdomain.com")
    cache.add.assert_called_once_with("newdomain.com")
    state.record_event.assert_called_once_with("domain_provisioned", "newdomain.com")

def test_unknown_mx_mismatch_no_provision():
    cache, jmap, _state = _setup()
    h = _handler(["recipient=user@wrongmx.com"])
    with patch("src.policy_daemon.mx_matches", return_value=False):
        h.handle()
    assert h.wfile.getvalue() == b"action=REJECT\n\n"
    jmap.provision_domain.assert_not_called()

def test_jmap_failure_does_not_cache_and_defers():
    cache, jmap, _state = _setup(jmap_ok=False)
    h = _handler(["recipient=user@newdomain.com"])
    with patch("src.policy_daemon.mx_matches", return_value=True):
        h.handle()
    assert h.wfile.getvalue() == b"action=DEFER_IF_PERMIT Service temporarily unavailable\n\n"
    cache.add.assert_not_called()

def test_no_at_sign_rejects_invalid_recipient():
    cache, jmap, _state = _setup()
    h = _handler(["recipient=invalid-no-at"])
    h.handle()
    assert h.wfile.getvalue() == b"action=REJECT Invalid recipient\n\n"
    jmap.provision_domain.assert_not_called()

def test_multiple_attrs_parsed_correctly():
    cache, jmap, _state = _setup(known={"example.com"})
    h = _handler([
        "request=smtpd_access_policy",
        "protocol_name=SMTP",
        "recipient=user@example.com",
        "sender=other@test.com",
    ])
    h.handle()
    assert h.wfile.getvalue() == b"action=OK\n\n"


def test_transient_mx_failure_defers():
    _cache, _jmap, _state = _setup()
    h = _handler(["recipient=user@example.com"])
    with patch("src.policy_daemon.mx_matches", side_effect=pd.MxLookupError("temporary")):
        h.handle()
    assert h.wfile.getvalue() == b"action=DEFER_IF_PERMIT DNS lookup failed, try again later\n\n"


def test_metric_failure_does_not_change_smtp_response():
    _cache, _jmap, state = _setup()
    state.record_event.side_effect = RuntimeError("disk full")
    h = _handler(["recipient=user@newdomain.com"])
    with patch("src.policy_daemon.mx_matches", return_value=True):
        h.handle()
    assert h.wfile.getvalue() == b"action=OK\n\n"


def test_changed_mail_config_rebuilds_jmap_client():
    _cache, old_jmap, _state = _setup(known={"example.com"})
    changed = MagicMock(
        mx_hostname="mail.tm-mails.com",
        jmap_url="https://new.example/jmap",
        jmap_token="new-token",
        catchall_address="new-admin@example.com",
    )
    pd._config_store.get.return_value = changed
    h = _handler(["recipient=user@example.com"])
    rebuilt = MagicMock()
    with patch("src.policy_daemon.JmapClient", return_value=rebuilt) as client_class:
        h.handle()
    client_class.assert_called_once_with(
        "https://new.example/jmap", "new-token", "new-admin@example.com"
    )
    assert pd._jmap is rebuilt
    assert pd._jmap is not old_jmap


def test_older_policy_read_cannot_reinstall_stale_jmap(monkeypatch):
    _cache, _jmap, _state = _setup(known={"example.com"})
    old_config = SimpleNamespace(
        jmap_url="https://older.example/jmap",
        jmap_token="older-token",
        catchall_address="older@example.com",
    )
    new_config = SimpleNamespace(
        jmap_url="https://newer.example/jmap",
        jmap_token="newer-token",
        catchall_address="newer@example.com",
    )
    old_read_started = threading.Event()
    release_old_read = threading.Event()
    new_done = threading.Event()
    errors = []

    def get_config():
        if threading.current_thread().name == "older-policy-read":
            old_read_started.set()
            release_old_read.wait(2)
            return old_config
        return new_config

    def build_client(url, _token, _catchall):
        return SimpleNamespace(url=url)

    pd._config_store.get.side_effect = get_config
    monkeypatch.setattr(pd, "_jmap_lock", threading.Lock())
    monkeypatch.setattr(pd, "JmapClient", build_client)

    def reload(done=None):
        try:
            pd._runtime()
        except Exception as exc:
            errors.append(exc)
        finally:
            if done:
                done.set()

    older = threading.Thread(target=reload, name="older-policy-read")
    newer = threading.Thread(target=reload, args=(new_done,), name="newer-policy-read")
    older.start()
    assert old_read_started.wait(1)
    newer.start()
    new_done.wait(0.5)
    release_old_read.set()
    older.join(2)
    newer.join(2)

    assert not errors
    assert not older.is_alive() and not newer.is_alive()
    assert pd._jmap.url == "https://newer.example/jmap"
