from __future__ import annotations
import dns.resolver

def mx_matches(domain: str, expected_mx: str) -> bool:
    try:
        answers = dns.resolver.resolve(domain, "MX")
        for rdata in answers:
            host = rdata.exchange.to_text().rstrip(".").lower()
            if host == expected_mx.lower():
                return True
        return False
    except Exception:
        return False
