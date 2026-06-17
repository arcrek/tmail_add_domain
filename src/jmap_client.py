from __future__ import annotations
import logging
import httpx

logger = logging.getLogger(__name__)

_USING = ["urn:ietf:params:jmap:core", "urn:stalwart:jmap"]

class JmapClient:
    def __init__(self, url: str, token: str, catchall_address: str):
        self._url = url
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self._catchall = catchall_address

    def provision_domain(self, domain: str) -> bool:
        payload = {
            "using": _USING,
            "methodCalls": [[
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
            ]],
        }
        try:
            resp = httpx.post(self._url, json=payload, headers=self._headers, timeout=10)
            resp.raise_for_status()
            method_resp = resp.json().get("methodResponses", [[]])[0]
            if method_resp[0] == "x:Domain/set" and "new-0" in method_resp[1].get("created", {}):
                return True
            logger.error("JMAP provision failed for %s: %s", domain, method_resp)
            return False
        except Exception as exc:
            logger.error("JMAP error provisioning %s: %s", domain, exc)
            return False

    def list_domains(self) -> list:
        payload = {
            "using": _USING,
            "methodCalls": [[
                "x:Domain/get",
                {"accountId": "b", "ids": None},
                "0",
            ]],
        }
        try:
            resp = httpx.post(self._url, json=payload, headers=self._headers, timeout=10)
            resp.raise_for_status()
            method_resp = resp.json().get("methodResponses", [[]])[0]
            if method_resp[0] == "x:Domain/get":
                return [d["name"] for d in method_resp[1].get("list", [])]
            logger.warning("Unexpected response for Domain/get: %s", method_resp)
            return []
        except Exception as exc:
            logger.error("JMAP list_domains error: %s", exc)
            return []
