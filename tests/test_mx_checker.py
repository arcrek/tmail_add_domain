from __future__ import annotations
import dns.resolver
import pytest
from unittest.mock import patch, MagicMock
from src.mx_checker import mx_matches

def _make_rdata(hostname: str) -> MagicMock:
    rdata = MagicMock()
    rdata.exchange.to_text.return_value = hostname + "."
    return rdata

def test_returns_true_when_mx_matches():
    with patch("src.mx_checker.dns.resolver.resolve") as mock:
        mock.return_value = [_make_rdata("mail.tm-mails.com")]
        assert mx_matches("newdomain.com", "mail.tm-mails.com") is True

def test_returns_false_when_mx_differs():
    with patch("src.mx_checker.dns.resolver.resolve") as mock:
        mock.return_value = [_make_rdata("mail.other.com")]
        assert mx_matches("newdomain.com", "mail.tm-mails.com") is False

@pytest.mark.parametrize("error", [dns.resolver.NXDOMAIN, dns.resolver.NoAnswer])
def test_returns_false_when_mx_does_not_exist(error):
    with patch("src.mx_checker.dns.resolver.resolve", side_effect=error):
        assert mx_matches("nonexistent.xyz", "mail.tm-mails.com") is False

def test_case_insensitive_match():
    with patch("src.mx_checker.dns.resolver.resolve") as mock:
        mock.return_value = [_make_rdata("MAIL.TM-MAILS.COM")]
        assert mx_matches("newdomain.com", "mail.tm-mails.com") is True

def test_returns_true_when_one_of_multiple_mx_matches():
    with patch("src.mx_checker.dns.resolver.resolve") as mock:
        mock.return_value = [
            _make_rdata("backup.other.com"),
            _make_rdata("mail.tm-mails.com"),
        ]
        assert mx_matches("newdomain.com", "mail.tm-mails.com") is True
