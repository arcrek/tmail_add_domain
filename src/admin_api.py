from __future__ import annotations

import base64
import binascii
from datetime import datetime, timedelta, timezone
import hashlib
import re
import secrets

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from src.api_auth import AddressValidationError, _domain, active_domains
from src.jmap_client import JmapClient


SITE_KEYS = {
    "app_name", "logo_data_url", "favicon_data_url", "primary_color", "accent_color", "language",
    "cookie_enabled", "cookie_text", "auto_sync_domains", "fetch_seconds",
    "message_limit", "local_part_min", "local_part_max", "forbidden_ids",
    "blocked_sender_domains", "header_html", "footer_html", "content_css", "ad_slots",
}
MAIL_KEYS = {"jmap_url", "jmap_token", "catchall_address", "mail_account_id", "retention_days"}
MASKED_SECRET = "********"
MAX_IMAGE_BYTES = 1024 * 1024
MAX_CONTENT_LENGTH = 100_000

router = APIRouter(prefix="/admin/api", tags=["admin"])


def _camel(key: str) -> str:
    head, *tail = key.split("_")
    return head + "".join(part.title() for part in tail)


def _session_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _session(request: Request) -> dict[str, object]:
    token = request.cookies.get("tmail_admin")
    if not token:
        raise HTTPException(401, "Admin session required")
    token_hash = _session_hash(token)
    session = request.app.state.state_store.get_admin_session(token_hash, datetime.now(timezone.utc))
    if session is None:
        raise HTTPException(401, "Invalid admin session")
    return {**session, "token_hash": token_hash}


def _csrf(
    session: dict[str, object] = Depends(_session),
    csrf_token: str | None = Header(None, alias="X-CSRF-Token"),
) -> dict[str, object]:
    expected = session["csrf_token"]
    if not isinstance(csrf_token, str) or not isinstance(expected, str) or not secrets.compare_digest(csrf_token, expected):
        raise HTTPException(403, "CSRF token mismatch")
    return session


def _section(body: dict[str, object], name: str, keys: set[str]) -> dict[str, object]:
    value = body.get(name, {})
    if not isinstance(value, dict):
        raise HTTPException(422, f"{name} must be an object")
    aliases = {_camel(key): key for key in keys} | {key: key for key in keys}
    unknown = set(value) - set(aliases)
    if unknown:
        raise HTTPException(422, f"Unknown {name} settings")
    return {aliases[key]: item for key, item in value.items()}


def _integer(value: object, minimum: int, maximum: int, name: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise HTTPException(422, f"{name} must be between {minimum} and {maximum}")
    return value


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise HTTPException(422, f"{name} must be a string")
    return value


def _image(value: object, name: str) -> str:
    value = _string(value, name)
    if not value:
        return value
    match = re.fullmatch(r"data:image/[A-Za-z0-9.+-]+;base64,([A-Za-z0-9+/]*={0,2})", value)
    try:
        decoded = base64.b64decode(match.group(1), validate=True) if match else b""
    except (binascii.Error, ValueError):
        decoded = b""
    if not match or not decoded or len(decoded) > MAX_IMAGE_BYTES:
        raise HTTPException(422, f"{name} must be an image data URL no larger than 1 MiB")
    return value


def _list(value: object, name: str, normalize) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise HTTPException(422, f"{name} must be a list of strings")
    try:
        normalized = [normalize(item.strip()) for item in value]
    except (AddressValidationError, UnicodeError):
        raise HTTPException(422, f"{name} contains an invalid value") from None
    if any(not item for item in normalized):
        raise HTTPException(422, f"{name} contains an empty value")
    return sorted(set(normalized))


def _validate_site(values: dict[str, object]) -> dict[str, object]:
    result = dict(values)
    for key in ("app_name", "language", "cookie_text"):
        result[key] = _string(result[key], key)
    for key in ("cookie_enabled", "auto_sync_domains"):
        if type(result[key]) is not bool:
            raise HTTPException(422, f"{key} must be a boolean")
    result["fetch_seconds"] = _integer(result["fetch_seconds"], 10, 300, "fetch_seconds")
    result["message_limit"] = _integer(result["message_limit"], 1, 100, "message_limit")
    result["local_part_min"] = _integer(result["local_part_min"], 1, 64, "local_part_min")
    result["local_part_max"] = _integer(result["local_part_max"], 1, 64, "local_part_max")
    if result["local_part_min"] > result["local_part_max"]:
        raise HTTPException(422, "local_part_min must not exceed local_part_max")
    for key in ("primary_color", "accent_color"):
        color = _string(result[key], key).lower()
        if not re.fullmatch(r"#[0-9a-f]{6}", color):
            raise HTTPException(422, f"{key} must be a six-digit hex color")
        result[key] = color
    for key in ("logo_data_url", "favicon_data_url"):
        result[key] = _image(result[key], key)
    result["forbidden_ids"] = _list(result["forbidden_ids"], "forbidden_ids", str.lower)
    result["blocked_sender_domains"] = _list(result["blocked_sender_domains"], "blocked_sender_domains", _domain)
    for key in ("header_html", "footer_html", "content_css"):
        value = _string(result[key], key)
        if len(value) > MAX_CONTENT_LENGTH:
            raise HTTPException(422, f"{key} exceeds {MAX_CONTENT_LENGTH} characters")
        result[key] = value
    slots = result["ad_slots"]
    if not isinstance(slots, dict) or any(
        not isinstance(key, str) or not key.strip() or not isinstance(value, str) or len(value) > MAX_CONTENT_LENGTH
        for key, value in slots.items()
    ):
        raise HTTPException(422, f"ad_slots values must not exceed {MAX_CONTENT_LENGTH} characters")
    result["ad_slots"] = {key.strip(): value for key, value in slots.items()}
    return result


def _validate_mail(values: dict[str, object]) -> dict[str, object]:
    result = dict(values)
    for key in ("jmap_url", "jmap_token", "catchall_address", "mail_account_id"):
        result[key] = _string(result[key], key).strip()
    if not result["jmap_url"].startswith(("http://", "https://")) or not result["jmap_token"]:
        raise HTTPException(422, "JMAP URL and token are required")
    local, separator, domain = result["catchall_address"].rpartition("@")
    if not separator or not local:
        raise HTTPException(422, "catchall_address must be an email address")
    try:
        result["catchall_address"] = f"{local.lower()}@{_domain(domain)}"
    except AddressValidationError:
        raise HTTPException(422, "catchall_address must be an email address") from None
    result["retention_days"] = _integer(result["retention_days"], 1, 3650, "retention_days")
    return result


def _active_domains(request: Request, settings: dict[str, object] | None = None) -> list[str]:
    settings = settings or request.app.state.state_store.get_settings()
    if not settings["auto_sync_domains"]:
        return request.app.state.state_store.get_frozen_domains()
    return active_domains(
        request.app.state.config_store.get().cache_file,
        request.app.state.state_store,
    )


@router.post("/login")
def login(request: Request, body: dict[str, object] = Body(...)):
    password = body.get("password")
    expected = request.app.state.config_store.get().admin_password
    if not isinstance(password, str) or not secrets.compare_digest(password, expected):
        raise HTTPException(401, "Invalid password")
    session_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    request.app.state.state_store.create_admin_session(
        _session_hash(session_token), csrf_token, datetime.now(timezone.utc) + timedelta(hours=12)
    )
    response = JSONResponse({"csrfToken": csrf_token})
    response.set_cookie(
        "tmail_admin", session_token, max_age=12 * 60 * 60,
        httponly=True, samesite="strict", path="/admin",
    )
    return response


@router.post("/logout", status_code=204)
def logout(request: Request, session: dict[str, object] = Depends(_csrf)):
    request.app.state.state_store.delete_admin_session(session["token_hash"])
    response = Response(status_code=204)
    response.delete_cookie("tmail_admin", path="/admin")
    return response


@router.get("/settings")
def settings(request: Request, _session_value: dict[str, object] = Depends(_session)):
    site = request.app.state.state_store.get_settings()
    config = request.app.state.config_store.get()
    mail = {key: getattr(config, key) for key in MAIL_KEYS}
    mail["jmap_token"] = MASKED_SECRET
    return {
        "site": {_camel(key): site[key] for key in SITE_KEYS},
        "mailServer": {_camel(key): mail[key] for key in MAIL_KEYS},
        "domains": _active_domains(request, site),
        "lastSync": request.app.state.state_store.last_sync(),
    }


@router.put("/settings")
def update_settings(
    request: Request,
    body: dict[str, object] = Body(...),
    _session_value: dict[str, object] = Depends(_csrf),
):
    if set(body) - {"site", "mailServer"}:
        raise HTTPException(422, "Unknown settings section")
    site_updates = _section(body, "site", SITE_KEYS)
    mail_updates = _section(body, "mailServer", MAIL_KEYS)
    state = request.app.state.state_store
    current_site = state.get_settings()
    validated_site = _validate_site(current_site | site_updates)

    current_config = request.app.state.config_store.get()
    current_mail = {key: getattr(current_config, key) for key in MAIL_KEYS}
    if mail_updates.get("jmap_token") in {"", MASKED_SECRET}:
        mail_updates.pop("jmap_token")
    validated_mail = _validate_mail(current_mail | mail_updates)

    if mail_updates:
        saved = request.app.state.config_store.update({key: validated_mail[key] for key in mail_updates})
        request.app.state.jmap = JmapClient(saved.jmap_url, saved.jmap_token, saved.catchall_address)
    if site_updates:
        if current_site["auto_sync_domains"] and not validated_site["auto_sync_domains"]:
            state.replace_frozen_domains(_active_domains(request, current_site))
        state.update_settings({key: validated_site[key] for key in site_updates})
    return settings(request, _session_value)


@router.post("/sync-domains")
def sync_domains(request: Request, _session_value: dict[str, object] = Depends(_csrf)):
    state = request.app.state.state_store
    try:
        values = request.app.state.jmap.list_domains()
        if not values:
            raise ValueError("Stalwart returned no domains")
        domains = _list(values, "domains", _domain)
        if not domains:
            raise ValueError("Stalwart returned no valid domains")
    except Exception as exc:
        state.record_sync(False, type(exc).__name__)
        raise HTTPException(502, "Domain sync failed") from None
    request.app.state.domain_cache.replace(domains)
    if not state.get_settings()["auto_sync_domains"]:
        state.replace_frozen_domains(domains)
    state.record_sync(True, f"{len(domains)} domains")
    return {"domains": domains, "lastSync": state.last_sync()}


@router.post("/test-mail")
def test_mail(request: Request, _session_value: dict[str, object] = Depends(_csrf)):
    try:
        domains = request.app.state.jmap.list_domains()
        if domains is None:
            raise ValueError("Invalid domain response")
        config = request.app.state.config_store.get()
        account_id = config.mail_account_id or request.app.state.jmap.discover_mail_account_id()
        messages = request.app.state.jmap.message_counts(account_id)
    except Exception:
        raise HTTPException(502, "Mail connection failed") from None
    return {"ok": True, "domainCount": len(domains), "messages": messages}


@router.get("/dashboard")
def dashboard(request: Request, _session_value: dict[str, object] = Depends(_session)):
    config = request.app.state.config_store.get()
    account_id = config.mail_account_id or request.app.state.jmap.discover_mail_account_id()
    site = request.app.state.state_store.get_settings()
    domains = {
        "active": len(_active_domains(request, site)),
        **request.app.state.state_store.activity_summary(),
    }
    return {
        "messages": request.app.state.jmap.message_counts(account_id),
        "domains": domains,
        "autoSyncDomains": site["auto_sync_domains"],
        "lastSync": request.app.state.state_store.last_sync(),
    }
