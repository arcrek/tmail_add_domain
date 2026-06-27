from __future__ import annotations
import dns.resolver


class MxLookupError(Exception):
    """Transient DNS failure — caller should defer, not reject."""


def mx_matches(domain: str, expected_mx: str) -> bool:
    try:
        answers = dns.resolver.resolve(domain, "MX")
        for rdata in answers:
            host = rdata.exchange.to_text().rstrip(".").lower()
            if host == expected_mx.lower():
                return True
        return False
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return False
    except Exception as exc:
        raise MxLookupError(str(exc)) from exc
