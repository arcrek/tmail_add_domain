"""Delete emails older than retention_days from Stalwart via JMAP."""
from __future__ import annotations
import logging
import sys
from datetime import datetime, timedelta, timezone

import httpx

from .config import load_config
from .jmap_client import JmapClient

logger = logging.getLogger(__name__)

_USING = ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"]
_BATCH = 50


def _query_old_emails(client: httpx.Client, url: str, account_id: str, before_utc: str) -> list[str]:
    """Return up to _BATCH email IDs received before before_utc."""
    payload = {
        "using": _USING,
        "methodCalls": [[
            "Email/query",
            {
                "accountId": account_id,
                "filter": {"before": before_utc},
                "limit": _BATCH,
                "position": 0,
            },
            "0",
        ]],
    }
    resp = client.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    method_resp = resp.json().get("methodResponses", [[]])[0]
    if method_resp[0] == "Email/query":
        return method_resp[1].get("ids", [])
    logger.warning("Unexpected Email/query response: %s", method_resp)
    return []


def _destroy_emails(client: httpx.Client, url: str, account_id: str, ids: list[str]) -> int:
    """Destroy the given email IDs. Returns count of successfully destroyed."""
    payload = {
        "using": _USING,
        "methodCalls": [[
            "Email/set",
            {"accountId": account_id, "destroy": ids},
            "0",
        ]],
    }
    resp = client.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    method_resp = resp.json().get("methodResponses", [[]])[0]
    if method_resp[0] == "Email/set":
        destroyed = method_resp[1].get("destroyed", [])
        not_destroyed = method_resp[1].get("notDestroyed", {})
        if not_destroyed:
            logger.warning("Failed to destroy %d emails: %s", len(not_destroyed), not_destroyed)
        return len(destroyed)
    logger.warning("Unexpected Email/set response: %s", method_resp)
    return 0


def run(config_path: str) -> None:
    cfg = load_config(config_path)
    retention_days = getattr(cfg, "retention_days", 30)

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    before_utc = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

    logger.info("Deleting emails received before %s (retention: %d days)", before_utc, retention_days)

    headers = {
        "Authorization": f"Bearer {cfg.jmap_token}",
        "Content-Type": "application/json",
    }
    total_deleted = 0

    with httpx.Client(headers=headers) as client:
        account_id = cfg.mail_account_id or JmapClient(
            cfg.jmap_url, cfg.jmap_token, cfg.catchall_address, client=client
        ).discover_mail_account_id()
        while True:
            ids = _query_old_emails(client, cfg.jmap_url, account_id, before_utc)
            if not ids:
                break
            deleted = _destroy_emails(client, cfg.jmap_url, account_id, ids)
            total_deleted += deleted
            logger.info("Deleted batch of %d (total so far: %d)", deleted, total_deleted)

    logger.info("Done. Total emails deleted: %d", total_deleted)


if __name__ == "__main__":
    import os
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config_path = os.environ.get("TMAIL_CONFIG", "/var/lib/tmail-policy/config.json")
    try:
        run(config_path)
    except Exception as exc:
        logger.error("Janitor failed: %s", exc)
        sys.exit(1)
