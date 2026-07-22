from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re

from src.domain_cache import DomainCache


_LOCAL_PART = re.compile(r"^[a-z0-9][a-z0-9._+-]*[a-z0-9]$|^[a-z0-9]$")
_DOMAIN_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class AddressValidationError(ValueError):
    pass


def _domain(value: str) -> str:
    try:
        domain = value.encode("idna").decode("ascii").lower()
    except (AttributeError, UnicodeError):
        raise AddressValidationError("Invalid domain") from None
    if len(domain) > 253 or not domain or any(not _DOMAIN_LABEL.fullmatch(label) for label in domain.split(".")):
        raise AddressValidationError("Invalid domain")
    return domain


def _token_address(address: str) -> str:
    try:
        local, domain = address.split("@")
    except (AttributeError, ValueError):
        raise ValueError("Invalid address") from None
    return f"{local.lower()}@{_domain(domain)}"


def normalize_address(address: str, domains: list[str], settings: dict[str, object]) -> str:
    try:
        local, domain = address.split("@")
    except (AttributeError, ValueError):
        raise AddressValidationError("Invalid address") from None
    local = local.lower()
    domain = _domain(domain)
    try:
        allowed_domains = {_domain(value) for value in domains}
        minimum = int(settings["local_part_min"])
        maximum = int(settings["local_part_max"])
        forbidden = {str(value).lower() for value in settings["forbidden_ids"]}
    except (KeyError, TypeError, ValueError):
        raise AddressValidationError("Invalid address settings") from None
    if not _LOCAL_PART.fullmatch(local) or not minimum <= len(local) <= maximum or local in forbidden or domain not in allowed_domains:
        raise AddressValidationError("Invalid address")
    return f"{local}@{domain}"


class AddressToken:
    def __init__(self, secret: str):
        self._secret = secret.encode()

    @staticmethod
    def _encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    @staticmethod
    def _decode(value: str) -> bytes:
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("Invalid address token")
        try:
            return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("Invalid address token") from None

    def issue(self, address: str) -> str:
        payload = json.dumps({"address": _token_address(address), "v": 1}, separators=(",", ":")).encode()
        signature = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return f"{self._encode(payload)}.{self._encode(signature)}"

    def read(self, token: str) -> str:
        try:
            payload_part, signature_part = token.split(".")
        except (AttributeError, ValueError):
            raise ValueError("Invalid address token") from None
        payload = self._decode(payload_part)
        if not hmac.compare_digest(hmac.new(self._secret, payload, hashlib.sha256).digest(), self._decode(signature_part)):
            raise ValueError("Invalid address token")
        try:
            data = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("Invalid address token") from None
        if not isinstance(data, dict) or set(data) != {"address", "v"} or not isinstance(data["address"], str) or type(data["v"]) is not int or data["v"] != 1:
            raise ValueError("Invalid address token")
        return data["address"]


def active_domains(cache_file: str | DomainCache, state) -> list[str]:
    if not state.get_settings()["auto_sync_domains"]:
        return state.get_frozen_domains()
    cache = cache_file if isinstance(cache_file, DomainCache) else DomainCache(cache_file)
    cache.load()
    domains = []
    for value in cache.domains():
        try:
            domains.append(_domain(value))
        except AddressValidationError:
            pass
    return sorted(set(domains))
