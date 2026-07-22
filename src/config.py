from __future__ import annotations

import json
import os
import stat
import sys
import threading
from dataclasses import asdict, dataclass

@dataclass
class Config:
    jmap_url: str
    jmap_token: str
    mx_hostname: str
    catchall_address: str
    listen_addr: str
    listen_port: int
    cache_file: str
    retention_days: int = 30
    api_listen_addr: str = "127.0.0.1"
    api_listen_port: int = 8000
    api_token_secret: str = ""
    admin_password: str = ""
    state_db: str = "/var/lib/tmail-policy/state.db"
    frontend_dist: str = "/opt/tmail-policy/frontend/dist"
    mail_account_id: str = ""


_TOKEN_COMMAND = "python3 -c 'import secrets; print(secrets.token_urlsafe(32))'"


def validate_web_config(config: Config) -> Config:
    secret = config.api_token_secret
    password = config.admin_password
    token_invalid = (
        not isinstance(secret, str)
        or len(secret.strip()) < 32
        or secret.strip().lower().startswith("replace-with")
    )
    password_invalid = (
        not isinstance(password, str)
        or not password.strip()
        or password.strip().lower().startswith("replace-with")
    )
    errors = []
    if token_invalid:
        errors.append(
            "api_token_secret must contain at least 32 non-whitespace characters and not use a "
            f"placeholder. Generate one with: {_TOKEN_COMMAND}"
        )
    if password_invalid:
        errors.append("admin_password must not be empty or use a placeholder")
    if errors:
        raise ValueError("; ".join(errors))
    return config


def _config_from_dict(d: dict) -> Config:
    return Config(
        jmap_url=d["jmap_url"],
        jmap_token=d["jmap_token"],
        mx_hostname=d["mx_hostname"],
        catchall_address=d["catchall_address"],
        listen_addr=d["listen_addr"],
        listen_port=int(d["listen_port"]),
        cache_file=d["cache_file"],
        retention_days=int(d.get("retention_days", 30)),
        api_listen_addr=d.get("api_listen_addr", "127.0.0.1"),
        api_listen_port=int(d.get("api_listen_port", 8000)),
        api_token_secret=d.get("api_token_secret", ""),
        admin_password=d.get("admin_password", ""),
        state_db=d.get("state_db", "/var/lib/tmail-policy/state.db"),
        frontend_dist=d.get("frontend_dist", "/opt/tmail-policy/frontend/dist"),
        mail_account_id=d.get("mail_account_id", ""),
    )


def load_config(path: str) -> Config:
    with open(path) as f:
        d = json.load(f)
    for key in ("state_db", "frontend_dist"):
        if key in d and not os.path.isabs(d[key]):
            d[key] = os.path.join(os.path.dirname(path), d[key])
    return _config_from_dict(d)


def _install_runtime_config(path: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "w") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(sys.stdin.read())
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        raise


class ConfigStore:
    _EDITABLE = {"jmap_url", "jmap_token", "catchall_address", "mail_account_id", "retention_days"}

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._mtime = -1.0
        self._config = load_config(path)

    def get(self) -> Config:
        with self._lock:
            mtime = os.path.getmtime(self.path)
            if mtime != self._mtime:
                self._config = load_config(self.path)
                self._mtime = mtime
            return self._config

    def update(self, values: dict[str, object]) -> Config:
        unknown = set(values) - self._EDITABLE
        if unknown:
            raise ValueError(f"Config fields are not editable: {sorted(unknown)}")
        with self._lock:
            current = asdict(load_config(self.path))
            current.update(values)
            updated = _config_from_dict(current)
            mode = stat.S_IMODE(os.stat(self.path).st_mode)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as handle:
                os.chmod(tmp, mode)
                json.dump(current, handle, indent=2)
                handle.write("\n")
            os.replace(tmp, self.path)
            self._config = updated
            self._mtime = os.path.getmtime(self.path)
            return updated


def _main(args: list[str] | None = None) -> int:
    args = sys.argv[1:] if args is None else args
    if len(args) == 2 and args[0] == "install-runtime":
        try:
            _install_runtime_config(args[1])
        except OSError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        return 0
    if len(args) != 2 or args[0] != "validate-web":
        print(
            "Usage: python3 -m src.config {validate-web|install-runtime} CONFIG",
            file=sys.stderr,
        )
        return 2
    try:
        validate_web_config(load_config(args[1]))
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
