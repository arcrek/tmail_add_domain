from __future__ import annotations
import io
import pytest
from unittest.mock import MagicMock, patch
import src.policy_daemon as pd

def _handler(lines: list) -> pd.PolicyHandler:
    h = pd.PolicyHandler.__new__(pd.PolicyHandler)
    h.rfile = io.BytesIO(("\n".join(lines) + "\n\n").encode())
    h.wfile = io.BytesIO()
    return h

def _setup(known: set = None, jmap_ok: bool = True):
    pd._config = MagicMock()
    pd._config.mx_hostname = "mail.tm-mails.com"
    cache = MagicMock()
    cache.contains.side_effect = lambda d: d in (known or set())
    pd._cache = cache
    jmap = MagicMock()
    jmap.provision_domain.return_value = jmap_ok
    pd._jmap = jmap
    return cache, jmap

def test_known_domain_instant_dunno():
    cache, jmap = _setup(known={"example.com"})
    h = _handler(["recipient=user@example.com"])
    h.handle()
    assert h.wfile.getvalue() == b"action=dunno\n\n"
    jmap.provision_domain.assert_not_called()

def test_unknown_mx_match_provisions_and_dunno():
    cache, jmap = _setup()
    h = _handler(["recipient=user@newdomain.com"])
    with patch("src.policy_daemon.mx_matches", return_value=True):
        h.handle()
    assert h.wfile.getvalue() == b"action=dunno\n\n"
    jmap.provision_domain.assert_called_once_with("newdomain.com")
    cache.add.assert_called_once_with("newdomain.com")

def test_unknown_mx_mismatch_no_provision():
    cache, jmap = _setup()
    h = _handler(["recipient=user@wrongmx.com"])
    with patch("src.policy_daemon.mx_matches", return_value=False):
        h.handle()
    assert h.wfile.getvalue() == b"action=dunno\n\n"
    jmap.provision_domain.assert_not_called()

def test_jmap_failure_does_not_cache_but_returns_dunno():
    cache, jmap = _setup(jmap_ok=False)
    h = _handler(["recipient=user@newdomain.com"])
    with patch("src.policy_daemon.mx_matches", return_value=True):
        h.handle()
    assert h.wfile.getvalue() == b"action=dunno\n\n"
    cache.add.assert_not_called()

def test_no_at_sign_returns_dunno_no_provision():
    cache, jmap = _setup()
    h = _handler(["recipient=invalid-no-at"])
    h.handle()
    assert h.wfile.getvalue() == b"action=dunno\n\n"
    jmap.provision_domain.assert_not_called()

def test_multiple_attrs_parsed_correctly():
    cache, jmap = _setup(known={"example.com"})
    h = _handler([
        "request=smtpd_access_policy",
        "protocol_name=SMTP",
        "recipient=user@example.com",
        "sender=other@test.com",
    ])
    h.handle()
    assert h.wfile.getvalue() == b"action=dunno\n\n"
