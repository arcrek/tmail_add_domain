from __future__ import annotations
from datetime import datetime, timedelta, timezone
import logging
from urllib.parse import quote

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

    def _call(self, method_calls: list, using: list[str]) -> list:
        response = self._client.post(
            self._url,
            json={"using": using, "methodCalls": method_calls},
            headers=self._headers,
            timeout=30,
        )
        response.raise_for_status()
        return response.json().get("methodResponses", [])

    def _get_session(self) -> dict:
        if self._session is None:
            response = self._client.get(self._url, headers=self._headers, timeout=30)
            response.raise_for_status()
            self._session = response.json()
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
            logger.error("JMAP provision failed for %s: %s", domain, method_resp)
            return False
        except Exception as exc:
            logger.error("JMAP error provisioning %s: %s", domain, exc)
            return False

    def list_domains(self) -> list:
        method_calls = [[
                "x:Domain/get",
                {"accountId": "b", "ids": None},
                "0",
            ]]
        try:
            method_resp = self._call(method_calls, _USING)[0]
            if method_resp[0] == "x:Domain/get":
                return [d["name"] for d in method_resp[1].get("list", [])]
            logger.warning("Unexpected response for Domain/get: %s", method_resp)
            return []
        except Exception as exc:
            logger.error("JMAP list_domains error: %s", exc)
            return []

    def discover_mail_account_id(self) -> str:
        session = self._get_session()
        account_id = session.get("primaryAccounts", {}).get(_MAIL_CAPABILITY)
        if account_id:
            return account_id
        for candidate, account in session.get("accounts", {}).items():
            capabilities = account.get("accountCapabilities", {})
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
        if len(method_responses) < 2 or method_responses[0][0] != "Email/query" or method_responses[1][0] != "Email/get":
            return 0, []
        return method_responses[0][1].get("total", 0), method_responses[1][1].get("list", [])

    def get_message(self, account_id: str, message_id: str) -> dict | None:
        method_responses = self._call([[
            "Email/get", {"accountId": account_id, "ids": [message_id], "properties": _MESSAGE_PROPERTIES}, "0",
        ]], _MAIL_USING)
        if not method_responses or method_responses[0][0] != "Email/get":
            return None
        messages = method_responses[0][1].get("list", [])
        return messages[0] if messages else None

    def set_seen(self, account_id: str, message_id: str, seen: bool) -> bool:
        method_responses = self._call([[
            "Email/set", {"accountId": account_id, "update": {message_id: {"keywords/$seen": seen}}}, "0",
        ]], _MAIL_USING)
        return bool(method_responses and method_responses[0][0] == "Email/set" and message_id in method_responses[0][1].get("updated", {}))

    def delete_message(self, account_id: str, message_id: str) -> bool:
        method_responses = self._call([[
            "Email/set", {"accountId": account_id, "destroy": [message_id]}, "0",
        ]], _MAIL_USING)
        return bool(method_responses and method_responses[0][0] == "Email/set" and message_id in method_responses[0][1].get("destroyed", []))

    def download_blob(self, account_id: str, blob_id: str, name: str) -> tuple[bytes, str]:
        download_url = self._get_session()["downloadUrl"]
        url = (download_url.replace("{accountId}", quote(account_id, safe=""))
            .replace("{blobId}", quote(blob_id, safe=""))
            .replace("{name}", quote(name, safe="")))
        response = self._client.get(url, headers=self._headers, timeout=30)
        response.raise_for_status()
        return response.content, response.headers.get("content-type", "application/octet-stream").split(";", 1)[0]

    def message_counts(self, account_id: str) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        seven_days = now - timedelta(days=7)
        method_responses = self._call([
            ["Email/query", {"accountId": account_id, "calculateTotal": True}, "stored"],
            ["Email/query", {"accountId": account_id, "calculateTotal": True, "filter": {"after": self._utc(today)}}, "today"],
            ["Email/query", {"accountId": account_id, "calculateTotal": True, "filter": {"after": self._utc(seven_days)}}, "sevenDays"],
        ], _MAIL_USING)
        totals = {response[2]: response[1].get("total", 0) for response in method_responses if response[0] == "Email/query"}
        return {"stored": totals.get("stored", 0), "today": totals.get("today", 0), "sevenDays": totals.get("sevenDays", 0)}

    @staticmethod
    def _utc(value: datetime) -> str:
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
