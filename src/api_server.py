from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import threading
import time
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api_auth import AddressToken, AddressValidationError, active_domains, normalize_address
from src.api_models import (
    AccountResource,
    AddressRequest,
    AttachmentResource,
    DomainResource,
    EmailAddress,
    HydraDomains,
    HydraError,
    HydraMessages,
    MessageResource,
    MessageSummary,
    SeenPatch,
    SiteResource,
    TokenResponse,
)
from src.api_state import StateStore
from src.config import ConfigStore
from src.jmap_client import JmapClient


_BEARER = HTTPBearer(auto_error=False)
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_ERROR_RESPONSES = {
    401: {"model": HydraError},
    404: {"model": HydraError},
    422: {"model": HydraError},
    502: {"model": HydraError},
}


def _stable_id(kind: str, value: str) -> str:
    return hashlib.sha256(f"{kind}:{value}".encode()).hexdigest()[:24]


def current_domains(request: Request) -> list[str]:
    cfg = request.app.state.config_store.get()
    return active_domains(cfg.cache_file, request.app.state.state_store)


def _address(request: Request, value: str) -> str:
    return normalize_address(value, current_domains(request), request.app.state.state_store.get_settings())


def bearer_address(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_BEARER),
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "Bearer token required")
    try:
        return _address(request, request.app.state.signer.read(credentials.credentials))
    except (AddressValidationError, ValueError):
        raise HTTPException(401, "Invalid bearer token") from None


def mail_account_id(request: Request) -> str:
    return request.app.state.config_store.get().mail_account_id or request.app.state.jmap.discover_mail_account_id()


def _email_value(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        candidate = value.get("email") or value.get("address")
        return candidate if isinstance(candidate, str) else None
    return None


def message_for_address(request: Request, address: str, message_id: str) -> tuple[str, dict]:
    account_id = mail_account_id(request)
    message = request.app.state.jmap.get_message(account_id, message_id)
    if not message:
        raise HTTPException(404, "Message not found")
    recipients = []
    for field in ("to", "cc", "bcc", "header:Delivered-To:asAddresses"):
        recipients.extend(message.get(field) or [])
    for recipient in recipients:
        value = _email_value(recipient)
        if value is None:
            continue
        try:
            if _address(request, value) == address:
                return account_id, message
        except AddressValidationError:
            pass
    raise HTTPException(404, "Message not found")


def _resource_time(message: dict) -> object:
    return message.get("receivedAt") or _EPOCH


def _emails(values: object) -> list[EmailAddress]:
    if not isinstance(values, list):
        return []
    result = []
    for value in values:
        address = _email_value(value)
        if address:
            result.append(EmailAddress(name=value.get("name", "") if isinstance(value, dict) else "", address=address))
    return result


def _sender(message: dict, blocked_domains: set[str]) -> EmailAddress:
    senders = _emails(message.get("from"))
    sender = senders[0] if senders else EmailAddress(name="", address="unknown@invalid")
    domain = sender.address.rpartition("@")[2].encode("idna").decode("ascii").lower()
    if domain in blocked_domains:
        return EmailAddress(name="Blocked sender", address="blocked@invalid")
    return sender


def _summary(message: dict, account_id: str, blocked_domains: set[str]) -> MessageSummary:
    message_id = str(message.get("id", ""))
    created = _resource_time(message)
    keywords = message.get("keywords") or {}
    return MessageSummary(
        iri=f"/messages/{message_id}",
        type="Message",
        id=message_id,
        account_id=account_id,
        msgid=str(message.get("messageId") or message_id),
        from_=_sender(message, blocked_domains),
        to=_emails(message.get("to")),
        subject=str(message.get("subject") or ""),
        intro=str(message.get("preview") or ""),
        seen=bool(keywords.get("$seen")),
        has_attachments=bool(message.get("hasAttachment") or message.get("attachments")),
        size=int(message.get("size") or 0),
        download_url=f"/sources/{message_id}",
        created_at=created,
        updated_at=created,
    )


def _body_parts(message: dict, field: str) -> list[str]:
    values = message.get("bodyValues") or {}
    result = []
    for part in message.get(field) or []:
        if not isinstance(part, dict):
            continue
        body = values.get(part.get("partId"), {})
        if isinstance(body, dict) and isinstance(body.get("value"), str):
            result.append(body["value"])
    return result


def _message(message: dict, account_id: str, blocked_domains: set[str]) -> MessageResource:
    summary = _summary(message, account_id, blocked_domains)
    created = _resource_time(message)
    attachments = []
    for attachment in message.get("attachments") or []:
        if not isinstance(attachment, dict) or not attachment.get("blobId"):
            continue
        blob_id = str(attachment["blobId"])
        attachments.append(AttachmentResource(
            iri=f"/messages/{summary.id}/attachments/{blob_id}",
            type="Attachment",
            id=blob_id,
            filename=str(attachment.get("name") or "attachment"),
            content_type=str(attachment.get("type") or "application/octet-stream"),
            disposition=str(attachment.get("disposition") or "attachment"),
            size=int(attachment.get("size") or 0),
            download_url=f"/messages/{summary.id}/attachments/{blob_id}",
            created_at=created,
            updated_at=created,
        ))
    return MessageResource(
        **summary.model_dump(),
        cc=_emails(message.get("cc")),
        bcc=_emails(message.get("bcc")),
        flagged=bool((message.get("keywords") or {}).get("$flagged")),
        text="\n".join(_body_parts(message, "textBody")),
        html=_body_parts(message, "htmlBody"),
        attachments=attachments,
    )


def _account(address: str) -> AccountResource:
    account_id = _stable_id("account", address)
    return AccountResource(
        iri=f"/accounts/{account_id}",
        type="Account",
        id=account_id,
        address=address,
        created_at=_EPOCH,
        updated_at=_EPOCH,
    )


def _error(status_code: int, title: str, description: str) -> JSONResponse:
    body = HydraError(title=title, description=description).model_dump(by_alias=True, mode="json")
    return JSONResponse(status_code=status_code, content=body)


def _download_headers(filename: str) -> dict[str, str]:
    safe_name = Path(filename.replace("\r", "").replace("\n", "")).name or "download"
    return {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(safe_name, safe='')}"}


def register_public_routes(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _exc: RequestValidationError):
        return _error(422, "Validation error", "The request is invalid")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, exc: StarletteHTTPException):
        descriptions = {401: "Authentication required", 404: "Resource not found", 429: "Too many requests"}
        description = exc.detail if isinstance(exc.detail, str) else descriptions.get(exc.status_code, "Request failed")
        return _error(exc.status_code, descriptions.get(exc.status_code, "Request error"), description)

    @app.exception_handler(Exception)
    async def upstream_error(_request: Request, _exc: Exception):
        return _error(502, "Mail service error", "The mail service is unavailable")

    @app.get("/domains", response_model=HydraDomains)
    def domains(request: Request):
        members = []
        for domain in current_domains(request):
            domain_id = _stable_id("domain", domain)
            members.append(DomainResource(
                iri=f"/domains/{domain_id}",
                type="Domain",
                id=domain_id,
                domain=domain,
                created_at=_EPOCH,
                updated_at=_EPOCH,
            ))
        return HydraDomains(total_items=len(members), member=members)

    @app.get("/domains/{domain_id}", response_model=DomainResource, responses=_ERROR_RESPONSES)
    def domain(request: Request, domain_id: str):
        for name in current_domains(request):
            if _stable_id("domain", name) == domain_id:
                return DomainResource(
                    iri=f"/domains/{domain_id}", type="Domain", id=domain_id, domain=name,
                    created_at=_EPOCH, updated_at=_EPOCH,
                )
        raise HTTPException(404, "Domain not found")

    @app.get("/site", response_model=SiteResource)
    def site(request: Request):
        settings = request.app.state.state_store.get_settings()
        return SiteResource(**{key: settings[key] for key in (
            "app_name", "logo_data_url", "favicon_data_url", "primary_color", "accent_color",
            "language", "cookie_enabled", "cookie_text", "fetch_seconds", "message_limit",
            "header_html", "footer_html", "content_css", "ad_slots",
        )})

    @app.post("/accounts", status_code=201, response_model=AccountResource, responses=_ERROR_RESPONSES)
    def accounts(body: AddressRequest, request: Request):
        try:
            return _account(_address(request, body.address))
        except AddressValidationError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.post(
        "/token",
        response_model=TokenResponse,
        responses=_ERROR_RESPONSES,
        summary="Issue a passwordless address token",
        description="Validates a whitelisted address and returns a stateless bearer token; no account or password is stored.",
    )
    def token(body: AddressRequest, request: Request):
        try:
            address = _address(request, body.address)
        except AddressValidationError as exc:
            raise HTTPException(422, str(exc)) from None
        return TokenResponse(id=_stable_id("account", address), token=request.app.state.signer.issue(address))

    @app.get("/me", response_model=AccountResource, responses=_ERROR_RESPONSES)
    def me(address: str = Depends(bearer_address)):
        return _account(address)

    @app.get("/messages", response_model=HydraMessages, responses=_ERROR_RESPONSES)
    def messages(request: Request, page: int = Query(1, ge=1), address: str = Depends(bearer_address)):
        settings = request.app.state.state_store.get_settings()
        limit = int(settings["message_limit"])
        account_id = mail_account_id(request)
        total, values = request.app.state.jmap.list_messages(account_id, address, limit, (page - 1) * limit)
        blocked = {str(value).encode("idna").decode("ascii").lower() for value in settings["blocked_sender_domains"]}
        return HydraMessages(total_items=total, member=[_summary(value, account_id, blocked) for value in values])

    @app.get("/messages/{message_id}", response_model=MessageResource, responses=_ERROR_RESPONSES)
    def message(message_id: str, request: Request, address: str = Depends(bearer_address)):
        account_id, value = message_for_address(request, address, message_id)
        settings = request.app.state.state_store.get_settings()
        blocked = {str(item).encode("idna").decode("ascii").lower() for item in settings["blocked_sender_domains"]}
        return _message(value, account_id, blocked)

    @app.patch("/messages/{message_id}", response_model=MessageResource, responses=_ERROR_RESPONSES)
    def patch_message(body: SeenPatch, message_id: str, request: Request, address: str = Depends(bearer_address)):
        account_id, value = message_for_address(request, address, message_id)
        if not request.app.state.jmap.set_seen(account_id, message_id, body.seen):
            raise HTTPException(502, "Could not update message")
        value = dict(value)
        value["keywords"] = dict(value.get("keywords") or {})
        value["keywords"]["$seen"] = body.seen
        settings = request.app.state.state_store.get_settings()
        blocked = {str(item).encode("idna").decode("ascii").lower() for item in settings["blocked_sender_domains"]}
        return _message(value, account_id, blocked)

    @app.delete("/messages/{message_id}", status_code=204, response_class=Response, responses=_ERROR_RESPONSES)
    def delete_message(message_id: str, request: Request, address: str = Depends(bearer_address)):
        account_id, _value = message_for_address(request, address, message_id)
        if not request.app.state.jmap.delete_message(account_id, message_id):
            raise HTTPException(502, "Could not delete message")
        return Response(status_code=204)

    @app.get("/messages/{message_id}/attachments/{blob_id}", responses=_ERROR_RESPONSES)
    def attachment(message_id: str, blob_id: str, request: Request, address: str = Depends(bearer_address)):
        account_id, value = message_for_address(request, address, message_id)
        match = next((item for item in value.get("attachments") or [] if item.get("blobId") == blob_id), None)
        if match is None:
            raise HTTPException(404, "Attachment not found")
        name = str(match.get("name") or "attachment")
        content, content_type = request.app.state.jmap.download_blob(account_id, blob_id, name)
        return StreamingResponse(iter([content]), media_type=content_type, headers=_download_headers(name))

    @app.get("/sources/{message_id}", responses=_ERROR_RESPONSES)
    def source(message_id: str, request: Request, address: str = Depends(bearer_address)):
        account_id, value = message_for_address(request, address, message_id)
        blob_id = value.get("blobId")
        if not blob_id:
            raise HTTPException(404, "Message source not found")
        name = f"{message_id}.eml"
        content, content_type = request.app.state.jmap.download_blob(account_id, str(blob_id), name)
        return StreamingResponse(iter([content]), media_type=content_type, headers=_download_headers(name))


def create_app(config_path: str) -> FastAPI:
    config_store = ConfigStore(config_path)
    cfg = config_store.get()
    if len(cfg.api_token_secret) < 32 or not cfg.admin_password:
        raise ValueError("api_token_secret and admin_password must be configured")
    state = StateStore(cfg.state_db)
    signer = AddressToken(cfg.api_token_secret)
    app = FastAPI(title="Temporary Mail API", docs_url="/docs", redoc_url="/redoc")
    app.state.config_store = config_store
    app.state.state_store = state
    app.state.signer = signer
    app.state.jmap = JmapClient(cfg.jmap_url, cfg.jmap_token, cfg.catchall_address)

    windows: dict[str, tuple[float, int]] = {}
    rate_lock = threading.Lock()

    @app.middleware("http")
    async def security(request: Request, call_next):
        if request.url.path in {"/token", "/admin/login"}:
            client_ip = request.client.host if request.client else "unknown"
            now = time.monotonic()
            with rate_lock:
                started, count = windows.get(client_ip, (now, 0))
                if now - started >= 60:
                    started, count = now, 0
                if count >= 10:
                    response = _error(429, "Too many requests", "Try again later")
                else:
                    windows[client_ip] = (started, count + 1)
                    response = None
            if response is not None:
                _set_security_headers(request, response)
                return response
        response = await call_next(request)
        _set_security_headers(request, response)
        return response

    register_public_routes(app)
    return app


def _set_security_headers(request: Request, response: Response) -> None:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    if request.url.path == "/docs":
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://cdn.jsdelivr.net; "
            "frame-ancestors 'none'"
        )
    else:
        response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
