from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class AddressRequest(ApiModel):
    address: str = Field(examples=["box@example.com"])


class TokenResponse(ApiModel):
    id: str = Field(examples=["a9f51566bd6705f7ea6ad54b"])
    token: str = Field(examples=["eyJhZGRyZXNzIjoiYm94QGV4YW1wbGUuY29tIiwidiI6MX0.signature"])


class _Resource(ApiModel):
    iri: str = Field(alias="@id")
    type: str = Field(alias="@type")
    id: str
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class AccountResource(_Resource):
    context: str = Field(default="/contexts/Account", alias="@context")
    address: str = Field(examples=["box@example.com"])
    quota: int = 0
    used: int = 0
    is_disabled: bool = Field(default=False, alias="isDisabled")
    is_deleted: bool = Field(default=False, alias="isDeleted")


class DomainResource(_Resource):
    context: str = Field(default="/contexts/Domain", alias="@context")
    domain: str = Field(examples=["example.com"])
    is_active: bool = Field(default=True, alias="isActive")
    is_private: bool = Field(default=False, alias="isPrivate")


class SiteResource(ApiModel):
    app_name: str = Field(alias="appName")
    logo_data_url: str = Field(alias="logoDataUrl")
    favicon_data_url: str = Field(alias="faviconDataUrl")
    primary_color: str = Field(alias="primaryColor")
    accent_color: str = Field(alias="accentColor")
    language: str
    cookie_enabled: bool = Field(alias="cookieEnabled")
    cookie_text: str = Field(alias="cookieText")
    fetch_seconds: int = Field(alias="fetchSeconds")
    message_limit: int = Field(alias="messageLimit")
    header_html: str = Field(alias="headerHtml")
    footer_html: str = Field(alias="footerHtml")
    content_css: str = Field(alias="contentCss")
    ad_slots: dict[str, Any] = Field(alias="adSlots")


class EmailAddress(ApiModel):
    name: str = ""
    address: str = Field(examples=["sender@example.net"])


class AttachmentResource(_Resource):
    context: str = Field(default="/contexts/Attachment", alias="@context")
    filename: str
    content_type: str = Field(alias="contentType")
    disposition: str
    size: int
    download_url: str = Field(alias="downloadUrl")


class MessageSummary(_Resource):
    context: str = Field(default="/contexts/Message", alias="@context")
    account_id: str = Field(alias="accountId")
    msgid: str
    from_: EmailAddress = Field(alias="from")
    to: list[EmailAddress]
    subject: str
    intro: str
    seen: bool
    is_deleted: bool = Field(default=False, alias="isDeleted")
    has_attachments: bool = Field(alias="hasAttachments")
    size: int
    download_url: str = Field(alias="downloadUrl")


class MessageResource(MessageSummary):
    cc: list[EmailAddress] = []
    bcc: list[EmailAddress] = []
    flagged: bool = False
    text: str = ""
    html: list[str] = []
    attachments: list[AttachmentResource] = []


class SeenPatch(ApiModel):
    seen: bool


class HydraDomains(ApiModel):
    context: str = Field(default="/contexts/Domain", alias="@context")
    iri: str = Field(default="/domains", alias="@id")
    type: str = Field(default="hydra:Collection", alias="@type")
    total_items: int = Field(alias="hydra:totalItems")
    member: list[DomainResource] = Field(alias="hydra:member")


class HydraMessages(ApiModel):
    context: str = Field(default="/contexts/Message", alias="@context")
    iri: str = Field(default="/messages", alias="@id")
    type: str = Field(default="hydra:Collection", alias="@type")
    total_items: int = Field(alias="hydra:totalItems")
    member: list[MessageSummary] = Field(alias="hydra:member")


class HydraError(ApiModel):
    context: str = Field(default="/contexts/Error", alias="@context")
    type: str = Field(default="hydra:Error", alias="@type")
    title: str = Field(alias="hydra:title")
    description: str = Field(alias="hydra:description")
