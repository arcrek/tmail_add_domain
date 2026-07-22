from __future__ import annotations
from collections.abc import Iterator
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import logging
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

logger = logging.getLogger(__name__)

_USING = ["urn:ietf:params:jmap:core", "urn:stalwart:jmap"]
_MAIL_USING = ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"]
_MAIL_CAPABILITY = "urn:ietf:params:jmap:mail"
_SUMMARY_PROPERTIES = [
    "id", "blobId", "threadId", "from", "to", "cc", "bcc", "subject", "preview", "keywords",
    "hasAttachment", "size", "receivedAt", "header:Delivered-To:asAddresses",
]
_MESSAGE_PROPERTIES = _SUMMARY_PROPERTIES + [
    "bodyValues", "textBody", "htmlBody", "attachments", "bodyStructure",
]


class JmapUpstreamError(RuntimeError):
    def __init__(self):
        super().__init__("JMAP upstream request failed")


class _BlobStream(Iterator[bytes]):
    def __init__(self, chunks: Iterator[bytes], resources: ExitStack):
        self._chunks = chunks
        self._resources = resources
        self._closed = False

    def __iter__(self):
        return self

    def __next__(self) -> bytes:
        if self._closed:
            raise StopIteration
        try:
            return next(self._chunks)
        except StopIteration:
            self.close()
            raise
        except Exception:
            try:
                self.close()
            except Exception:
                pass
            raise JmapUpstreamError() from None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            close = getattr(self._chunks, "close", None)
            if close is not None:
                close()
        except Exception:
            pass
        try:
            self._resources.close()
        except Exception:
            raise JmapUpstreamError() from None


class JmapClient:
    def __init__(self, url: str, token: str, catchall_address: str, client=None):
        self._url = url
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self._catchall = catchall_address
        self._client = client or httpx
        self._session = None
        self._api_url = url

    def _call(self, method_calls: list, using: list[str]) -> list:
        try:
            response = self._client.post(
                self._api_url,
                json={"using": using, "methodCalls": method_calls},
                headers=self._headers,
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            raise JmapUpstreamError() from None
        if not isinstance(payload, dict) or not isinstance(payload.get("methodResponses"), list):
            raise JmapUpstreamError()
        method_responses = payload["methodResponses"]
        if len(method_responses) != len(method_calls):
            raise JmapUpstreamError()
        for expected, received in zip(method_calls, method_responses):
            if (
                not isinstance(received, list)
                or len(received) != 3
                or received[0] == "error"
                or received[0] != expected[0]
                or received[2] != expected[2]
                or not isinstance(received[1], dict)
            ):
                raise JmapUpstreamError()
        return method_responses

    def _get_session(self) -> dict:
        if self._session is None:
            parts = urlsplit(self._url)
            well_known = urlunsplit((parts.scheme, parts.netloc, "/.well-known/jmap", "", ""))
            for url in dict.fromkeys((self._url, well_known)):
                try:
                    response = self._client.get(
                        url, headers=self._headers, timeout=30, follow_redirects=True
                    )
                    response.raise_for_status()
                    payload = response.json()
                except Exception:
                    continue
                if isinstance(payload, dict):
                    self._session = payload
                    api_url = payload.get("apiUrl")
                    if isinstance(api_url, str) and api_url:
                        self._api_url = api_url
                    break
            if self._session is None:
                raise JmapUpstreamError()
        return self._session

    def provision_domain(self, domain: str) -> bool:
        method_calls = [[
                "x:Domain/set",
                {
                    "accountId": "b",
                    "create": {
                        "new-0": {
                            "name": domain,
                            "isEnabled": True,
                            "allowRelaying": True,
                            "catchAllAddress": self._catchall,
                            "certificateManagement": {"@type": "Manual"},
                            "dnsManagement": {"@type": "Manual"},
                            "reportAddressUri": "mailto:postmaster",
                            "subAddressing": {"@type": "Enabled"},
                            "dkimManagement": {"@type": "Manual"},
                        }
                    },
                },
                "0",
            ]]
        try:
            method_resp = self._call(method_calls, _USING)[0]
            if method_resp[0] == "x:Domain/set":
                data = method_resp[1]
                if "new-0" in data.get("created", {}):
                    return True
                not_created = data.get("notCreated", {}).get("new-0", {})
                if not_created.get("type") == "alreadyExists":
                    return True
            logger.error("JMAP provision failed for %s", domain)
            return False
        except Exception:
            logger.error("JMAP error provisioning %s", domain)
            return False

    def list_domains(self) -> list:
        method_calls = [[
                "x:Domain/get",
                {"accountId": "b", "ids": None},
                "0",
            ]]
        method_resp = self._call(method_calls, _USING)[0]
        values = method_resp[1].get("list")
        if not isinstance(values, list) or any(
            not isinstance(domain, dict) or not isinstance(domain.get("name"), str)
            for domain in values
        ):
            raise JmapUpstreamError()
        return [domain["name"] for domain in values]

    def discover_mail_account_id(self) -> str:
        session = self._get_session()
        primary_accounts = session.get("primaryAccounts", {})
        accounts = session.get("accounts", {})
        if not isinstance(primary_accounts, dict) or not isinstance(accounts, dict):
            raise JmapUpstreamError()
        account_id = primary_accounts.get(_MAIL_CAPABILITY)
        if account_id:
            if not isinstance(account_id, str):
                raise JmapUpstreamError()
            return account_id
        for candidate, account in accounts.items():
            if not isinstance(candidate, str) or not isinstance(account, dict):
                raise JmapUpstreamError()
            capabilities = account.get("accountCapabilities", {})
            if not isinstance(capabilities, dict):
                raise JmapUpstreamError()
            if account.get("isPersonal") and _MAIL_CAPABILITY in capabilities:
                return candidate
        raise ValueError("JMAP session has no personal mail account")

    def list_messages(self, account_id: str, address: str, limit: int, position: int) -> tuple[int, list[dict]]:
        method_responses = self._call([
            ["Email/query", {
                "accountId": account_id,
                "filter": {"operator": "OR", "conditions": [
                    {"to": address}, {"header": ["Delivered-To", address]},
                ]},
                "limit": limit,
                "position": position,
                "calculateTotal": True,
            }, "q"],
            ["Email/get", {
                "accountId": account_id,
                "#ids": {"resultOf": "q", "name": "Email/query", "path": "/ids"},
                "properties": _SUMMARY_PROPERTIES,
            }, "g"],
        ], _MAIL_USING)
        total = method_responses[0][1].get("total")
        messages = method_responses[1][1].get("list")
        if type(total) is not int or total < 0 or not isinstance(messages, list) or any(
            not isinstance(message, dict) for message in messages
        ):
            raise JmapUpstreamError()
        return total, messages

    def get_message(self, account_id: str, message_id: str) -> dict | None:
        method_responses = self._call([[
            "Email/get", {
                "accountId": account_id,
                "ids": [message_id],
                "properties": _MESSAGE_PROPERTIES,
                "fetchTextBodyValues": True,
                "fetchHTMLBodyValues": True,
            }, "0",
        ]], _MAIL_USING)
        messages = method_responses[0][1].get("list", [])
        if not isinstance(messages, list) or any(not isinstance(message, dict) for message in messages):
            raise JmapUpstreamError()
        return messages[0] if messages else None

    def set_seen(self, account_id: str, message_id: str, seen: bool) -> bool:
        method_responses = self._call([[
            "Email/set", {"accountId": account_id, "update": {message_id: {"keywords/$seen": seen}}}, "0",
        ]], _MAIL_USING)
        updated = method_responses[0][1].get("updated", {})
        if not isinstance(updated, dict):
            raise JmapUpstreamError()
        return message_id in updated

    def delete_message(self, account_id: str, message_id: str) -> bool:
        method_responses = self._call([[
            "Email/set", {"accountId": account_id, "destroy": [message_id]}, "0",
        ]], _MAIL_USING)
        destroyed = method_responses[0][1].get("destroyed", [])
        if not isinstance(destroyed, list):
            raise JmapUpstreamError()
        return message_id in destroyed

    def download_blob(
        self,
        account_id: str,
        blob_id: str,
        name: str,
        content_type: str = "application/octet-stream",
    ) -> tuple[Iterator[bytes], str]:
        download_url = self._get_session().get("downloadUrl")
        if not isinstance(download_url, str):
            raise JmapUpstreamError()
        substitutions = {
            "accountId": account_id,
            "blobId": blob_id,
            "name": name,
            "type": content_type,
        }
        url = download_url
        for variable, value in substitutions.items():
            url = url.replace(f"{{{variable}}}", quote(value, safe=""))
        if "{" in url or "}" in url:
            raise JmapUpstreamError()

        resources = ExitStack()
        try:
            client = resources.enter_context(httpx.Client()) if self._client is httpx else self._client
            response = resources.enter_context(client.stream(
                "GET", url, headers=self._headers, timeout=30
            ))
            response.raise_for_status()
            chunks = iter(response.iter_bytes())
        except Exception:
            try:
                resources.close()
            except Exception:
                pass
            raise JmapUpstreamError() from None

        return _BlobStream(chunks, resources), content_type

    def message_counts(self, account_id: str) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        seven_days = now - timedelta(days=7)
        method_responses = self._call([
            ["Email/query", {"accountId": account_id, "calculateTotal": True}, "stored"],
            ["Email/query", {"accountId": account_id, "calculateTotal": True, "filter": {"after": self._utc(today)}}, "today"],
            ["Email/query", {"accountId": account_id, "calculateTotal": True, "filter": {"after": self._utc(seven_days)}}, "sevenDays"],
        ], _MAIL_USING)
        totals = {}
        for response in method_responses:
            total = response[1].get("total")
            if type(total) is not int or total < 0:
                raise JmapUpstreamError()
            totals[response[2]] = total
        return {"stored": totals.get("stored", 0), "today": totals.get("today", 0), "sevenDays": totals.get("sevenDays", 0)}

    @staticmethod
    def _utc(value: datetime) -> str:
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
