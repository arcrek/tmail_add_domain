# Auto-Add Domain via JMAP — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy a Postfix policy daemon that auto-provisions any domain in Stalwart (with catch-all to `admin@mail.tm-mails.com`) the moment the first email arrives for it, with no email lost.

**Architecture:** A Python TCP server on `127.0.0.1:10030` implements the Postfix policy protocol. Per RCPT TO, it checks an in-memory domain cache (backed by `domains.json`), then does a DNS MX lookup, and on match calls the Stalwart JMAP API to create the domain and catch-all in one request. Postfix listens on `:25`, delivers accepted mail to Stalwart via LMTP on `127.0.0.1:24`. Stalwart's external SMTP listener is moved off `:25`.

**Tech Stack:** Python 3.8+, `dnspython`, `httpx`, `pytest`, Postfix, Stalwart (existing)

## Global Constraints

- Python 3.8+ compatible — use `from __future__ import annotations` in all src files
- All code in `src/`, all tests in `tests/`
- Remote server SSH target stored in env var `$SERVER` (e.g. `root@mail.tm-mails.com`)
- Never hardcode credentials in source files — config loaded from `config.json` at runtime
- Spec: `docs/superpowers/specs/2026-06-17-auto-add-domain-design.md`

---

## File Map

```
src/
  config.py          # load Config dataclass from config.json
  domain_cache.py    # in-memory set + atomic JSON persistence
  mx_checker.py      # DNS MX lookup
  jmap_client.py     # Stalwart JMAP API calls
  policy_daemon.py   # TCP server, Postfix policy protocol, orchestration

tests/
  test_config.py
  test_domain_cache.py
  test_mx_checker.py
  test_jmap_client.py
  test_policy_daemon.py

deploy/
  tmail-policy.service   # systemd unit
  deploy.sh              # copies files to remote, sets up service
  postfix_main_snippet.cf  # lines to add to /etc/postfix/main.cf
  accepted_domains       # wildcard Postfix domain map

config.example.json      # template — copy to server, fill in token
requirements.txt         # dnspython, httpx
requirements-dev.txt     # pytest
```

---

### Task 1: Project scaffold

**Files:**
- Create: `src/` `tests/` `deploy/` directories
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `config.example.json`

- [ ] **Step 1: Create directories**

```bash
mkdir -p src tests deploy
touch src/__init__.py tests/__init__.py
```

- [ ] **Step 2: Write `requirements.txt`**

```
dnspython>=2.3.0
httpx>=0.24.0
```

- [ ] **Step 3: Write `requirements-dev.txt`**

```
-r requirements.txt
pytest>=7.0.0
```

- [ ] **Step 4: Write `config.example.json`**

```json
{
  "jmap_url": "https://mail.tm-mails.com/jmap/",
  "jmap_token": "REPLACE_WITH_YOUR_API_TOKEN",
  "mx_hostname": "mail.tm-mails.com",
  "catchall_address": "admin@mail.tm-mails.com",
  "listen_addr": "127.0.0.1",
  "listen_port": 10030,
  "cache_file": "/var/lib/tmail-policy/domains.json"
}
```

- [ ] **Step 5: Install dev dependencies**

```bash
pip install -r requirements-dev.txt
```

Expected: packages install without error.

- [ ] **Step 6: Commit**

```bash
git init
git add requirements.txt requirements-dev.txt config.example.json src/__init__.py tests/__init__.py
git commit -m "feat: project scaffold"
```

---

### Task 2: Config module

**Files:**
- Create: `src/config.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Produces: `Config` dataclass, `load_config(path: str) -> Config`

- [ ] **Step 1: Write the failing test — `tests/test_config.py`**

```python
from __future__ import annotations
import json
import pytest
from src.config import load_config, Config

def test_load_valid_config(tmp_path):
    data = {
        "jmap_url": "https://example.com/jmap/",
        "jmap_token": "tok123",
        "mx_hostname": "mail.example.com",
        "catchall_address": "admin@example.com",
        "listen_addr": "127.0.0.1",
        "listen_port": 10030,
        "cache_file": "/tmp/domains.json",
    }
    f = tmp_path / "config.json"
    f.write_text(json.dumps(data))
    cfg = load_config(str(f))
    assert isinstance(cfg, Config)
    assert cfg.jmap_token == "tok123"
    assert cfg.listen_port == 10030

def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/config.json")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_config.py -v
```

Expected: `ImportError` or `ModuleNotFoundError`

- [ ] **Step 3: Write `src/config.py`**

```python
from __future__ import annotations
import json
from dataclasses import dataclass

@dataclass
class Config:
    jmap_url: str
    jmap_token: str
    mx_hostname: str
    catchall_address: str
    listen_addr: str
    listen_port: int
    cache_file: str

def load_config(path: str) -> Config:
    with open(path) as f:
        d = json.load(f)
    return Config(
        jmap_url=d["jmap_url"],
        jmap_token=d["jmap_token"],
        mx_hostname=d["mx_hostname"],
        catchall_address=d["catchall_address"],
        listen_addr=d["listen_addr"],
        listen_port=int(d["listen_port"]),
        cache_file=d["cache_file"],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_config.py -v
```

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/config.py tests/test_config.py
git commit -m "feat: config loading module"
```

---

### Task 3: Domain cache module

**Files:**
- Create: `src/domain_cache.py`
- Create: `tests/test_domain_cache.py`

**Interfaces:**
- Consumes: nothing
- Produces: `DomainCache(cache_file: str)` with methods `.load()`, `.contains(domain: str) -> bool`, `.add(domain: str)`, `.add_many(domains: list)`

- [ ] **Step 1: Write the failing tests — `tests/test_domain_cache.py`**

```python
from __future__ import annotations
import json
import os
import pytest
from src.domain_cache import DomainCache

def test_empty_on_missing_file(tmp_path):
    cache = DomainCache(str(tmp_path / "domains.json"))
    cache.load()
    assert not cache.contains("example.com")

def test_load_existing_file(tmp_path):
    f = tmp_path / "domains.json"
    f.write_text('["example.com", "test.org"]')
    cache = DomainCache(str(f))
    cache.load()
    assert cache.contains("example.com")
    assert cache.contains("test.org")
    assert not cache.contains("other.net")

def test_add_persists_to_disk(tmp_path):
    path = str(tmp_path / "sub" / "domains.json")
    cache = DomainCache(path)
    cache.load()
    cache.add("new.com")
    assert cache.contains("new.com")
    with open(path) as f:
        data = json.load(f)
    assert "new.com" in data

def test_corrupt_file_resets_to_empty(tmp_path):
    f = tmp_path / "domains.json"
    f.write_text("not valid json{{")
    cache = DomainCache(str(f))
    cache.load()
    assert not cache.contains("example.com")

def test_no_tmp_file_left_after_write(tmp_path):
    path = str(tmp_path / "domains.json")
    cache = DomainCache(path)
    cache.load()
    cache.add("a.com")
    assert not os.path.exists(path + ".tmp")

def test_add_many(tmp_path):
    path = str(tmp_path / "domains.json")
    cache = DomainCache(path)
    cache.load()
    cache.add_many(["a.com", "b.com", "c.com"])
    assert cache.contains("a.com")
    assert cache.contains("c.com")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_domain_cache.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Write `src/domain_cache.py`**

```python
from __future__ import annotations
import json
import os
import threading

class DomainCache:
    def __init__(self, cache_file: str):
        self._file = cache_file
        self._lock = threading.Lock()
        self._domains: set = set()

    def load(self) -> None:
        try:
            with open(self._file) as f:
                data = json.load(f)
            self._domains = set(data)
        except (FileNotFoundError, json.JSONDecodeError):
            self._domains = set()

    def contains(self, domain: str) -> bool:
        with self._lock:
            return domain in self._domains

    def add(self, domain: str) -> None:
        with self._lock:
            self._domains.add(domain)
            self._persist()

    def add_many(self, domains: list) -> None:
        with self._lock:
            self._domains.update(domains)
            self._persist()

    def _persist(self) -> None:
        tmp = self._file + ".tmp"
        os.makedirs(os.path.dirname(os.path.abspath(self._file)), exist_ok=True)
        with open(tmp, "w") as f:
            json.dump(sorted(self._domains), f)
        os.replace(tmp, self._file)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_domain_cache.py -v
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/domain_cache.py tests/test_domain_cache.py
git commit -m "feat: domain cache with atomic disk persistence"
```

---

### Task 4: DNS MX checker module

**Files:**
- Create: `src/mx_checker.py`
- Create: `tests/test_mx_checker.py`

**Interfaces:**
- Consumes: nothing
- Produces: `mx_matches(domain: str, expected_mx: str) -> bool`

- [ ] **Step 1: Write the failing tests — `tests/test_mx_checker.py`**

```python
from __future__ import annotations
import pytest
from unittest.mock import patch, MagicMock
from src.mx_checker import mx_matches

def _make_rdata(hostname: str) -> MagicMock:
    rdata = MagicMock()
    rdata.exchange.to_text.return_value = hostname + "."
    return rdata

def test_returns_true_when_mx_matches():
    with patch("src.mx_checker.dns.resolver.resolve") as mock:
        mock.return_value = [_make_rdata("mail.tm-mails.com")]
        assert mx_matches("newdomain.com", "mail.tm-mails.com") is True

def test_returns_false_when_mx_differs():
    with patch("src.mx_checker.dns.resolver.resolve") as mock:
        mock.return_value = [_make_rdata("mail.other.com")]
        assert mx_matches("newdomain.com", "mail.tm-mails.com") is False

def test_returns_false_on_nxdomain():
    with patch("src.mx_checker.dns.resolver.resolve", side_effect=Exception("NXDOMAIN")):
        assert mx_matches("nonexistent.xyz", "mail.tm-mails.com") is False

def test_case_insensitive_match():
    with patch("src.mx_checker.dns.resolver.resolve") as mock:
        mock.return_value = [_make_rdata("MAIL.TM-MAILS.COM")]
        assert mx_matches("newdomain.com", "mail.tm-mails.com") is True

def test_returns_true_when_one_of_multiple_mx_matches():
    with patch("src.mx_checker.dns.resolver.resolve") as mock:
        mock.return_value = [
            _make_rdata("backup.other.com"),
            _make_rdata("mail.tm-mails.com"),
        ]
        assert mx_matches("newdomain.com", "mail.tm-mails.com") is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_mx_checker.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Write `src/mx_checker.py`**

```python
from __future__ import annotations
import dns.resolver

def mx_matches(domain: str, expected_mx: str) -> bool:
    try:
        answers = dns.resolver.resolve(domain, "MX")
        for rdata in answers:
            host = rdata.exchange.to_text().rstrip(".").lower()
            if host == expected_mx.lower():
                return True
        return False
    except Exception:
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_mx_checker.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/mx_checker.py tests/test_mx_checker.py
git commit -m "feat: DNS MX checker"
```

---

### Task 5: JMAP client module

**Files:**
- Create: `src/jmap_client.py`
- Create: `tests/test_jmap_client.py`

**Interfaces:**
- Consumes: nothing
- Produces: `JmapClient(url, token, catchall_address)` with `.provision_domain(domain: str) -> bool` and `.list_domains() -> list`

- [ ] **Step 1: Write the failing tests — `tests/test_jmap_client.py`**

```python
from __future__ import annotations
import pytest
from unittest.mock import patch, MagicMock
from src.jmap_client import JmapClient

CLIENT = JmapClient(
    "https://mail.tm-mails.com/jmap/",
    "token123",
    "admin@mail.tm-mails.com",
)

def _mock_response(json_body: dict) -> MagicMock:
    m = MagicMock()
    m.json.return_value = json_body
    m.raise_for_status = MagicMock()
    return m

def test_provision_domain_success():
    resp = {"methodResponses": [["x:Domain/set", {"created": {"new-0": {"id": "abc"}}}, "0"]]}
    with patch("src.jmap_client.httpx.post", return_value=_mock_response(resp)):
        assert CLIENT.provision_domain("newdomain.com") is True

def test_provision_domain_jmap_not_created():
    resp = {"methodResponses": [["x:Domain/set", {"notCreated": {"new-0": {"type": "alreadyExists"}}}, "0"]]}
    with patch("src.jmap_client.httpx.post", return_value=_mock_response(resp)):
        assert CLIENT.provision_domain("newdomain.com") is False

def test_provision_domain_network_error():
    with patch("src.jmap_client.httpx.post", side_effect=Exception("connection refused")):
        assert CLIENT.provision_domain("newdomain.com") is False

def test_list_domains_success():
    resp = {"methodResponses": [["x:Domain/get", {"list": [{"name": "example.com"}, {"name": "test.org"}]}, "0"]]}
    with patch("src.jmap_client.httpx.post", return_value=_mock_response(resp)):
        result = CLIENT.list_domains()
    assert result == ["example.com", "test.org"]

def test_list_domains_network_error_returns_empty():
    with patch("src.jmap_client.httpx.post", side_effect=Exception("timeout")):
        assert CLIENT.list_domains() == []

def test_list_domains_unexpected_response_returns_empty():
    resp = {"methodResponses": [["error", {"type": "unknownMethod"}, "0"]]}
    with patch("src.jmap_client.httpx.post", return_value=_mock_response(resp)):
        assert CLIENT.list_domains() == []

def test_provision_sends_correct_domain_name():
    captured = {}
    def fake_post(url, json, headers, timeout):
        captured["payload"] = json
        resp = MagicMock()
        resp.json.return_value = {"methodResponses": [["x:Domain/set", {"created": {"new-0": {"id": "x"}}}, "0"]]}
        resp.raise_for_status = MagicMock()
        return resp
    with patch("src.jmap_client.httpx.post", side_effect=fake_post):
        CLIENT.provision_domain("example.com")
    create_obj = captured["payload"]["methodCalls"][0][1]["create"]["new-0"]
    assert create_obj["name"] == "example.com"
    assert create_obj["catchAllAddress"] == "admin@mail.tm-mails.com"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_jmap_client.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Write `src/jmap_client.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_jmap_client.py -v
```

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/jmap_client.py tests/test_jmap_client.py
git commit -m "feat: JMAP client for domain provisioning and listing"
```

---

### Task 6: Policy daemon

**Files:**
- Create: `src/policy_daemon.py`
- Create: `tests/test_policy_daemon.py`

**Interfaces:**
- Consumes: `Config` from `src.config`, `DomainCache` from `src.domain_cache`, `mx_matches` from `src.mx_checker`, `JmapClient` from `src.jmap_client`
- Produces: runnable daemon via `python -m src.policy_daemon` or `TMAIL_CONFIG=... python src/policy_daemon.py`

- [ ] **Step 1: Write the failing tests — `tests/test_policy_daemon.py`**

```python
from __future__ import annotations
import io
import pytest
from unittest.mock import MagicMock, patch
import src.policy_daemon as pd

def _handler(lines: list) -> pd.PolicyHandler:
    h = pd.PolicyHandler.__new__(pd.PolicyHandler)
    h.rfile = io.BytesIO(("\n".join(lines) + "\n\n").encode())
    h.wfile = io.BytesIO()
    return h

def _setup(known: set = None, jmap_ok: bool = True):
    pd._config = MagicMock()
    pd._config.mx_hostname = "mail.tm-mails.com"
    cache = MagicMock()
    cache.contains.side_effect = lambda d: d in (known or set())
    pd._cache = cache
    jmap = MagicMock()
    jmap.provision_domain.return_value = jmap_ok
    pd._jmap = jmap
    return cache, jmap

def test_known_domain_instant_dunno():
    cache, jmap = _setup(known={"example.com"})
    h = _handler(["recipient=user@example.com"])
    h.handle()
    assert h.wfile.getvalue() == b"action=dunno\n\n"
    jmap.provision_domain.assert_not_called()

def test_unknown_mx_match_provisions_and_dunno():
    cache, jmap = _setup()
    h = _handler(["recipient=user@newdomain.com"])
    with patch("src.policy_daemon.mx_matches", return_value=True):
        h.handle()
    assert h.wfile.getvalue() == b"action=dunno\n\n"
    jmap.provision_domain.assert_called_once_with("newdomain.com")
    cache.add.assert_called_once_with("newdomain.com")

def test_unknown_mx_mismatch_no_provision():
    cache, jmap = _setup()
    h = _handler(["recipient=user@wrongmx.com"])
    with patch("src.policy_daemon.mx_matches", return_value=False):
        h.handle()
    assert h.wfile.getvalue() == b"action=dunno\n\n"
    jmap.provision_domain.assert_not_called()

def test_jmap_failure_does_not_cache_but_returns_dunno():
    cache, jmap = _setup(jmap_ok=False)
    h = _handler(["recipient=user@newdomain.com"])
    with patch("src.policy_daemon.mx_matches", return_value=True):
        h.handle()
    assert h.wfile.getvalue() == b"action=dunno\n\n"
    cache.add.assert_not_called()

def test_no_at_sign_returns_dunno_no_provision():
    cache, jmap = _setup()
    h = _handler(["recipient=invalid-no-at"])
    h.handle()
    assert h.wfile.getvalue() == b"action=dunno\n\n"
    jmap.provision_domain.assert_not_called()

def test_multiple_attrs_parsed_correctly():
    cache, jmap = _setup(known={"example.com"})
    h = _handler([
        "request=smtpd_access_policy",
        "protocol_name=SMTP",
        "recipient=user@example.com",
        "sender=other@test.com",
    ])
    h.handle()
    assert h.wfile.getvalue() == b"action=dunno\n\n"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_policy_daemon.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Write `src/policy_daemon.py`**

```python
from __future__ import annotations
import logging
import os
import socketserver
import sys

from src.config import load_config
from src.domain_cache import DomainCache
from src.jmap_client import JmapClient
from src.mx_checker import mx_matches

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

_config = None
_cache: DomainCache = None
_jmap: JmapClient = None


class PolicyHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        attrs = {}
        for raw in self.rfile:
            line = raw.decode(errors="replace").strip()
            if not line:
                break
            if "=" in line:
                k, v = line.split("=", 1)
                attrs[k.strip()] = v.strip()

        recipient = attrs.get("recipient", "")
        domain = recipient.split("@")[-1].lower() if "@" in recipient else ""

        if domain and not _cache.contains(domain):
            if mx_matches(domain, _config.mx_hostname):
                ok = _jmap.provision_domain(domain)
                if ok:
                    _cache.add(domain)
                    logger.info("Provisioned: %s", domain)
                else:
                    logger.error("JMAP provision failed: %s", domain)
            else:
                logger.debug("MX mismatch, skipping: %s", domain)

        self.wfile.write(b"action=dunno\n\n")


def main() -> None:
    global _config, _cache, _jmap
    config_path = os.environ.get("TMAIL_CONFIG", "/opt/tmail-policy/config.json")
    _config = load_config(config_path)

    _cache = DomainCache(_config.cache_file)
    _cache.load()

    _jmap = JmapClient(_config.jmap_url, _config.jmap_token, _config.catchall_address)

    existing = _jmap.list_domains()
    if existing:
        _cache.add_many(existing)
        logger.info("Pre-loaded %d domains from Stalwart", len(existing))

    server = socketserver.ThreadingTCPServer(
        (_config.listen_addr, _config.listen_port),
        PolicyHandler,
    )
    server.allow_reuse_address = True
    logger.info("Listening on %s:%d", _config.listen_addr, _config.listen_port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run all tests**

```bash
pytest tests/ -v
```

Expected: all tests pass (no failures)

- [ ] **Step 5: Commit**

```bash
git add src/policy_daemon.py tests/test_policy_daemon.py
git commit -m "feat: policy daemon TCP server"
```

---

### Task 7: Deployment artifacts

**Files:**
- Create: `deploy/tmail-policy.service`
- Create: `deploy/deploy.sh`
- Create: `deploy/postfix_main_snippet.cf`
- Create: `deploy/accepted_domains`

- [ ] **Step 1: Write `deploy/tmail-policy.service`**

```ini
[Unit]
Description=Tmail Policy Daemon
After=network.target

[Service]
User=tmail-policy
WorkingDirectory=/opt/tmail-policy
Environment=TMAIL_CONFIG=/opt/tmail-policy/config.json
ExecStart=/usr/bin/python3 -m src.policy_daemon
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Write `deploy/postfix_main_snippet.cf`**

```
# --- tmail-policy additions ---
myhostname = mail.tm-mails.com
mydomain = tm-mails.com
myorigin = $myhostname

inet_interfaces = all
inet_protocols = ipv4

# Postfix does not own local delivery — Stalwart does
mydestination =
local_recipient_maps =
local_transport = error:local delivery disabled

# Forward accepted mail to Stalwart via LMTP
virtual_transport = lmtp:127.0.0.1:24
virtual_mailbox_domains = /etc/postfix/accepted_domains

mynetworks = 127.0.0.0/8
relay_domains =

# Policy daemon
smtpd_recipient_restrictions =
    permit_mynetworks,
    check_policy_service inet:127.0.0.1:10030,
    permit
# --- end tmail-policy additions ---
```

- [ ] **Step 3: Write `deploy/accepted_domains`**

```
*    OK
```

- [ ] **Step 4: Write `deploy/deploy.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

SERVER="${1:?Usage: ./deploy.sh user@hostname}"
REMOTE_DIR="/opt/tmail-policy"

echo "==> Installing Python dependencies on remote"
ssh "$SERVER" "pip3 install dnspython httpx"

echo "==> Creating remote directories"
ssh "$SERVER" "mkdir -p $REMOTE_DIR /var/lib/tmail-policy"

echo "==> Uploading daemon source"
ssh "$SERVER" "mkdir -p $REMOTE_DIR/src"
scp src/__init__.py src/config.py src/domain_cache.py src/mx_checker.py \
    src/jmap_client.py src/policy_daemon.py \
    "$SERVER:$REMOTE_DIR/src/"

echo "==> Uploading systemd unit"
scp deploy/tmail-policy.service "$SERVER:/etc/systemd/system/"

echo "==> Creating service user (idempotent)"
ssh "$SERVER" "id tmail-policy &>/dev/null || useradd -r -s /sbin/nologin tmail-policy"

echo "==> Setting permissions"
ssh "$SERVER" "
  chown -R tmail-policy:tmail-policy $REMOTE_DIR /var/lib/tmail-policy
  [ -f $REMOTE_DIR/config.json ] && chmod 600 $REMOTE_DIR/config.json || true
"

echo "==> Enabling and restarting service"
ssh "$SERVER" "systemctl daemon-reload && systemctl enable tmail-policy && systemctl restart tmail-policy"

echo "==> Status"
ssh "$SERVER" "systemctl status tmail-policy --no-pager -l"
```

- [ ] **Step 5: Make deploy script executable and commit**

```bash
chmod +x deploy/deploy.sh
git add deploy/
git commit -m "feat: deployment artifacts"
```

---

### Task 8: Stalwart reconfiguration on remote server

> SSH to the remote server for all steps in this task. Replace `$SERVER` with your actual host (e.g. `root@mail.tm-mails.com`).

- [ ] **Step 1: Find the Stalwart config file**

```bash
ssh $SERVER "find /etc /opt /usr -name 'config.toml' 2>/dev/null | grep stalwart; \
  systemctl cat stalwart-mail 2>/dev/null | grep -E 'ExecStart|WorkingDir'"
```

Expected: a path like `/etc/stalwart/config.toml` or `/opt/stalwart/etc/config.toml`

- [ ] **Step 2: Identify the current SMTP listener binding**

```bash
ssh $SERVER "grep -A5 -B2 'port.*25\|listener.*smtp' /PATH/TO/config.toml"
```

Look for a block like:
```toml
[server.listener.smtp]
bind = ["0.0.0.0:25"]
```

- [ ] **Step 3: Check LMTP listener exists**

```bash
ssh $SERVER "grep -A5 'lmtp\|port.*24' /PATH/TO/config.toml"
```

Expected: an LMTP listener block with `bind = ["127.0.0.1:24"]`. If missing, add it in the next step.

- [ ] **Step 4: Edit Stalwart config to move SMTP off port 25**

Change the SMTP listener's bind from `0.0.0.0:25` to `127.0.0.1:25` (keeps it available for local tools but frees the public port). If an LMTP listener is missing, add:

```toml
[server.listener.lmtp]
bind = ["127.0.0.1:24"]
protocol = "lmtp"
```

Edit on the remote:
```bash
ssh $SERVER "cp /PATH/TO/config.toml /PATH/TO/config.toml.bak"
# then edit with nano/vim or use sed for the bind line:
ssh $SERVER "sed -i 's/\"0\.0\.0\.0:25\"/\"127.0.0.1:25\"/' /PATH/TO/config.toml"
```

- [ ] **Step 5: Stop Stalwart, start Postfix, restart Stalwart**

```bash
ssh $SERVER "systemctl stop stalwart-mail"
ssh $SERVER "systemctl start postfix"
ssh $SERVER "systemctl start stalwart-mail"
```

- [ ] **Step 6: Verify port ownership**

```bash
ssh $SERVER "ss -tlnp | grep -E ':25|:24'"
```

Expected output:
```
LISTEN  0  100  0.0.0.0:25   ...  postfix/master
LISTEN  0  100  127.0.0.1:24 ...  stalwart
```

---

### Task 9: Postfix installation and configuration on remote server

- [ ] **Step 1: Install Postfix**

```bash
ssh $SERVER "DEBIAN_FRONTEND=noninteractive apt install -y postfix"
```

If prompted during install, it will use the default "Local only" config — that is fine, we overwrite it in the next steps.

- [ ] **Step 2: Back up existing main.cf**

```bash
ssh $SERVER "cp /etc/postfix/main.cf /etc/postfix/main.cf.bak"
```

- [ ] **Step 3: Upload the config snippet**

```bash
scp deploy/postfix_main_snippet.cf $SERVER:/tmp/
ssh $SERVER "cat /tmp/postfix_main_snippet.cf >> /etc/postfix/main.cf"
```

- [ ] **Step 4: Upload the accepted_domains map and build it**

```bash
scp deploy/accepted_domains $SERVER:/etc/postfix/accepted_domains
ssh $SERVER "postmap /etc/postfix/accepted_domains"
```

- [ ] **Step 5: Validate Postfix config**

```bash
ssh $SERVER "postfix check"
```

Expected: no errors (warnings about TLS are OK at this stage)

- [ ] **Step 6: Restart Postfix**

```bash
ssh $SERVER "systemctl restart postfix && systemctl status postfix --no-pager"
```

Expected: `Active: active (running)`

- [ ] **Step 7: Verify port 25 is owned by Postfix**

```bash
ssh $SERVER "ss -tlnp | grep :25"
```

Expected: `postfix/master` in the output

---

### Task 10: Deploy policy daemon to remote server

- [ ] **Step 1: Copy config template to remote and fill in credentials**

```bash
scp config.example.json $SERVER:/opt/tmail-policy/config.json
ssh $SERVER "nano /opt/tmail-policy/config.json"
# Fill in jmap_token with the actual API token
```

- [ ] **Step 2: Set config file permissions**

```bash
ssh $SERVER "chmod 600 /opt/tmail-policy/config.json && chown tmail-policy:tmail-policy /opt/tmail-policy/config.json"
```

- [ ] **Step 3: Run deploy script**

```bash
./deploy/deploy.sh $SERVER
```

Expected: ends with `Active: active (running)`

- [ ] **Step 4: Verify daemon is listening**

```bash
ssh $SERVER "ss -tlnp | grep :10030"
```

Expected: Python process listening on `127.0.0.1:10030`

- [ ] **Step 5: Verify daemon logs show domain pre-load**

```bash
ssh $SERVER "journalctl -u tmail-policy -n 20 --no-pager"
```

Expected: log line like `Pre-loaded N domains from Stalwart` (N may be 0 if this is a fresh Stalwart)

- [ ] **Step 6: Test the policy protocol manually**

```bash
ssh $SERVER "printf 'recipient=test@mail.tm-mails.com\n\n' | nc 127.0.0.1 10030"
```

Expected: `action=dunno`

---

### Task 11: End-to-end verification

- [ ] **Step 1: Find a domain with MX pointing to mail.tm-mails.com**

Pick a test domain you control that has `MX mail.tm-mails.com`. Verify:
```bash
dig MX yourtestdomain.com +short
```

Expected: `10 mail.tm-mails.com.`

- [ ] **Step 2: Confirm domain is NOT yet in Stalwart**

Check the policy daemon cache:
```bash
ssh $SERVER "cat /var/lib/tmail-policy/domains.json"
```

Confirm `yourtestdomain.com` is not listed.

- [ ] **Step 3: Send a test email to the domain**

```bash
echo "Test body" | mail -s "Test subject" testuser@yourtestdomain.com
```

Or use swaks:
```bash
swaks --to testuser@yourtestdomain.com --server mail.tm-mails.com
```

- [ ] **Step 4: Verify domain was auto-provisioned**

```bash
ssh $SERVER "cat /var/lib/tmail-policy/domains.json"
```

Expected: `yourtestdomain.com` now appears in the list.

- [ ] **Step 5: Check daemon log for provisioning message**

```bash
ssh $SERVER "journalctl -u tmail-policy -n 20 --no-pager"
```

Expected: `Provisioned: yourtestdomain.com`

- [ ] **Step 6: Verify the email was delivered to admin@mail.tm-mails.com**

Check the inbox of `admin@mail.tm-mails.com` — the test email should have arrived.

- [ ] **Step 7: Send a second email to the same domain**

```bash
echo "Second email" | mail -s "Second test" testuser@yourtestdomain.com
```

Check daemon logs — should see NO new provisioning log (domain is now cached). Email still delivers.

- [ ] **Step 8: Test MX mismatch is handled gracefully**

Send to a domain whose MX does NOT point to `mail.tm-mails.com`:
```bash
swaks --to anyone@notourserver.com --server mail.tm-mails.com
```

Expected: Stalwart returns a 550 rejection. Daemon logs show no provision attempt.
