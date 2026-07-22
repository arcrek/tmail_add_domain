from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
import sqlite3


DEFAULT_SETTINGS = {
    "app_name": "Temporary Inbox",
    "logo_data_url": "",
    "favicon_data_url": "",
    "primary_color": "#252525",
    "accent_color": "#3348c8",
    "language": "en",
    "cookie_enabled": False,
    "cookie_text": "",
    "auto_sync_domains": True,
    "fetch_seconds": 20,
    "message_limit": 15,
    "local_part_min": 3,
    "local_part_max": 32,
    "forbidden_ids": [],
    "blocked_sender_domains": [],
    "header_html": "",
    "footer_html": "",
    "content_css": "",
    "ad_slots": {},
}


class StateStore:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS frozen_domains (domain TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS admin_sessions (
                  token_hash TEXT PRIMARY KEY,
                  csrf_token TEXT NOT NULL,
                  expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS activity (
                  id INTEGER PRIMARY KEY,
                  kind TEXT NOT NULL,
                  domain TEXT,
                  detail TEXT,
                  created_at TEXT NOT NULL
                );
            """)
            conn.executemany(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                ((key, json.dumps(value)) for key, value in DEFAULT_SETTINGS.items()),
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def get_settings(self) -> dict[str, object]:
        with self._connect() as conn:
            return {row["key"]: json.loads(row["value"]) for row in conn.execute("SELECT key, value FROM settings")}

    def update_settings(self, values: dict[str, object]) -> None:
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                ((key, json.dumps(value)) for key, value in values.items()),
            )

    def get_frozen_domains(self) -> list[str]:
        with self._connect() as conn:
            return [row["domain"] for row in conn.execute("SELECT domain FROM frozen_domains ORDER BY domain")]

    def replace_frozen_domains(self, domains: list[str]) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM frozen_domains")
            conn.executemany(
                "INSERT INTO frozen_domains (domain) VALUES (?)",
                ((domain,) for domain in sorted(set(domains))),
            )

    def create_admin_session(self, token_hash: str, csrf_token: str, expires_at: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO admin_sessions (token_hash, csrf_token, expires_at) VALUES (?, ?, ?)",
                (token_hash, csrf_token, expires_at.isoformat()),
            )

    def get_admin_session(self, token_hash: str, now: datetime) -> dict[str, object] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT token_hash, csrf_token, expires_at FROM admin_sessions WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
            if row is None or datetime.fromisoformat(row["expires_at"]) <= now:
                conn.execute("DELETE FROM admin_sessions WHERE token_hash = ?", (token_hash,))
                return None
            return dict(row)

    def delete_admin_session(self, token_hash: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM admin_sessions WHERE token_hash = ?", (token_hash,))

    def record_event(self, kind: str, domain: str | None = None, detail: str | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO activity (kind, domain, detail, created_at) VALUES (?, ?, ?, ?)",
                (kind, domain, detail, datetime.now(timezone.utc).isoformat()),
            )

    def record_sync(self, success: bool, detail: str) -> None:
        self.record_event("sync_success" if success else "sync_failure", detail=detail)

    def last_sync(self) -> dict[str, object]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT kind, detail, created_at FROM activity "
                "WHERE kind IN ('sync_success', 'sync_failure') ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return {}
            return {
                "success": row["kind"] == "sync_success",
                "detail": row["detail"],
                "created_at": row["created_at"],
            }

    def activity_summary(self) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        today = now.date().isoformat()
        seven_days = (now - timedelta(days=7)).isoformat()
        with self._connect() as conn:
            domains_today = conn.execute(
                "SELECT COUNT(*) FROM activity WHERE kind = 'domain_provisioned' AND created_at >= ?",
                (today,),
            ).fetchone()[0]
            domains_seven_days = conn.execute(
                "SELECT COUNT(*) FROM activity WHERE kind = 'domain_provisioned' AND created_at >= ?",
                (seven_days,),
            ).fetchone()[0]
            recent_domains = [
                dict(row)
                for row in conn.execute(
                    "SELECT domain, created_at FROM activity WHERE kind = 'domain_provisioned' "
                    "ORDER BY id DESC LIMIT 10"
                )
            ]
            return {
                "domainsToday": domains_today,
                "domainsSevenDays": domains_seven_days,
                "recentDomains": recent_domains,
            }
