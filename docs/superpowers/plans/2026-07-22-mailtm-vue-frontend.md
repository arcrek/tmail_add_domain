# Vue Temporary-Mail Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a passwordless Vue temporary-mail frontend, a Mail.tm-shaped FastAPI/JMAP API, automatic domain-whitelist synchronization, and a protected administration area with mail-activity metrics.

**Architecture:** Keep the Postfix policy daemon as the only SMTP/domain-provisioning path. Add a same-origin FastAPI service that serves the Vite build, translates public Mail.tm-shaped resources to Stalwart JMAP, signs stateless address tokens, and stores only site settings/admin sessions/activity in SQLite.

**Tech Stack:** Python 3.8+, FastAPI, Uvicorn, Pydantic, SQLite, httpx, pytest, Vue 3, TypeScript, Vite, Vitest

## Global Constraints

- Preserve the existing Postfix policy protocol and domain-provisioning decisions.
- Never expose or log Stalwart tokens, admin passwords, address tokens, message bodies, or attachment contents.
- Temporary users have no stored account or password; `POST /token` accepts only an email address.
- Every message/blob/source operation must recheck the bearer token's recipient.
- Domain-sync failure must retain the last valid whitelist.
- Render message HTML and configurable HTML in sandboxed iframes, never with Vue `v-html` in the application document.
- Use Mail.tm resource names and Hydra collection fields from `https://api.mail.tm/docs.jsonld` while documenting the intentional passwordless authentication difference.
- Do not add Pinia, Vue Router, a UI framework, an ORM, or a JWT package.
- Spec: `docs/superpowers/specs/2026-07-22-mailtm-vue-frontend-design.md`
- Before Task 1, run `python3 -m pip install -r requirements-dev.txt` so failing tests fail for behavior rather than missing pytest.

---

## File Map

```text
src/
  config.py              # validated runtime config plus atomic reload/update
  domain_cache.py        # existing domain cache plus safe snapshots/replacement
  jmap_client.py         # existing domain calls plus mail/blob/session operations
  api_auth.py            # address normalization and stateless HMAC bearer tokens
  api_state.py           # SQLite settings, admin sessions, and activity events
  api_models.py          # typed Mail.tm/Hydra and admin request/response models
  admin_api.py           # protected admin routes
  api_server.py          # FastAPI app, public routes, middleware, static SPA fallback
  policy_daemon.py       # existing flow plus hot config and best-effort metric write

frontend/
  package.json
  package-lock.json
  tsconfig.json
  vite.config.ts
  index.html
  src/
    vite-env.d.ts
    main.ts
    App.vue
    api.ts
    route.ts
    session.ts
    types.ts
    styles.css
    components/
      AddressPanel.vue
      InboxView.vue
      MessageReader.vue
      SandboxFrame.vue
    admin/
      AdminApp.vue
      DashboardTab.vue
      GeneralTab.vue
      MailServerTab.vue
      DomainsTab.vue
      ContentTab.vue
    tests/
      route.test.ts
      SandboxFrame.test.ts

tests/
  test_api_auth.py
  test_api_state.py
  test_jmap_mail.py
  test_public_api.py
  test_admin_api.py
  test_api_static.py

deploy/
  tmail-api.service

config.example.json      # new API, token-signing, admin, state, and frontend fields
requirements.txt         # FastAPI and Uvicorn
README.md                # local build/run and deployment documentation
```

---

### Task 1: Runtime configuration and SQLite state

**Files:**
- Modify: `src/config.py`
- Create: `src/api_state.py`
- Modify: `config.example.json`
- Modify: `requirements.txt`
- Modify: `.gitignore`
- Test: `tests/test_config.py`
- Test: `tests/test_api_state.py`

**Interfaces:**
- Produces: `ConfigStore(path: str).get() -> Config`
- Produces: `ConfigStore(path: str).update(values: dict[str, object]) -> Config`
- Produces: `StateStore(path: str)` with settings, frozen-domain, admin-session, and activity methods

- [ ] **Step 1: Add failing config tests**

Change the existing config import to `from src.config import Config, ConfigStore, load_config`, then append to `tests/test_config.py`:

```python
def test_frontend_defaults_are_loaded(tmp_path):
    data = {
        "jmap_url": "https://example.com/jmap/",
        "jmap_token": "tok",
        "mx_hostname": "mail.example.com",
        "catchall_address": "admin@example.com",
        "listen_addr": "127.0.0.1",
        "listen_port": 10030,
        "cache_file": str(tmp_path / "domains.json"),
        "api_token_secret": "a" * 32,
        "admin_password": "secret",
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data))
    cfg = load_config(str(path))
    assert cfg.api_listen_addr == "127.0.0.1"
    assert cfg.api_listen_port == 8000
    assert cfg.state_db.endswith("state.db")
    assert cfg.frontend_dist.endswith("frontend/dist")


def test_legacy_policy_config_still_loads_without_web_secrets(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "jmap_url": "https://example.com/jmap/",
        "jmap_token": "tok",
        "mx_hostname": "mail.example.com",
        "catchall_address": "admin@example.com",
        "listen_addr": "127.0.0.1",
        "listen_port": 10030,
        "cache_file": str(tmp_path / "domains.json"),
    }))
    cfg = load_config(str(path))
    assert cfg.api_token_secret == ""
    assert cfg.admin_password == ""


def test_config_store_atomically_updates_allowed_fields(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "jmap_url": "https://old.example/jmap/",
        "jmap_token": "old",
        "mx_hostname": "mail.example.com",
        "catchall_address": "admin@example.com",
        "listen_addr": "127.0.0.1",
        "listen_port": 10030,
        "cache_file": str(tmp_path / "domains.json"),
        "api_token_secret": "a" * 32,
        "admin_password": "secret",
    }))
    store = ConfigStore(str(path))
    cfg = store.update({"jmap_url": "https://new.example/jmap/"})
    assert cfg.jmap_url == "https://new.example/jmap/"
    assert not (tmp_path / "config.json.tmp").exists()
```

- [ ] **Step 2: Run the config tests and confirm failure**

Run: `python3 -m pytest tests/test_config.py -q`  
Expected: FAIL because the API fields and `ConfigStore` do not exist.

- [ ] **Step 3: Implement reloadable atomic configuration**

In `src/config.py`, retain existing fields and add:

```python
import os
import threading
from dataclasses import asdict

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
            tmp = self.path + ".tmp"
            with open(tmp, "w") as handle:
                json.dump(current, handle, indent=2)
                handle.write("\n")
            os.replace(tmp, self.path)
            self._config = updated
            self._mtime = os.path.getmtime(self.path)
            return updated
```

Factor `load_config()` through `_config_from_dict(d: dict) -> Config` and resolve relative `state_db`/`frontend_dist` paths against the config file directory. Keep empty defaults for the new web secrets so existing policy-daemon and janitor configurations remain valid; `create_app()` must reject an API startup whose token secret is shorter than 32 characters or whose admin password is empty.

- [ ] **Step 4: Add failing state-store tests**

Create `tests/test_api_state.py`:

```python
from datetime import datetime, timedelta, timezone
from src.api_state import StateStore


def test_settings_and_frozen_domains_round_trip(tmp_path):
    store = StateStore(str(tmp_path / "state.db"))
    store.update_settings({"auto_sync_domains": False, "fetch_seconds": 20})
    store.replace_frozen_domains(["b.example", "a.example"])
    assert store.get_settings()["auto_sync_domains"] is False
    assert store.get_frozen_domains() == ["a.example", "b.example"]


def test_admin_session_expires(tmp_path):
    store = StateStore(str(tmp_path / "state.db"))
    now = datetime.now(timezone.utc)
    store.create_admin_session("hash", "csrf", now - timedelta(seconds=1))
    assert store.get_admin_session("hash", now) is None


def test_activity_summary_counts_domains(tmp_path):
    store = StateStore(str(tmp_path / "state.db"))
    store.record_event("domain_provisioned", "example.com")
    summary = store.activity_summary()
    assert summary["domainsToday"] == 1
    assert summary["recentDomains"][0]["domain"] == "example.com"
```

- [ ] **Step 5: Run the state tests and confirm failure**

Run: `python3 -m pytest tests/test_api_state.py -q`  
Expected: FAIL with `ModuleNotFoundError: src.api_state`.

- [ ] **Step 6: Implement `StateStore` with stdlib SQLite**

Create `src/api_state.py` with one connection per operation, `sqlite3.Row`, WAL mode, and this schema:

```sql
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
```

Use JSON values in `settings`. Seed exact defaults on first open:

```python
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
```

Implement the exact tested methods plus `delete_admin_session()`, `record_sync(success: bool, detail: str)`, and `last_sync() -> dict[str, object]`.

- [ ] **Step 7: Update dependencies and example configuration**

Add `fastapi>=0.110,<1` and `uvicorn>=0.29,<1` to `requirements.txt`; `requirements-dev.txt` already inherits httpx through `-r requirements.txt`. Add all new fields to `config.example.json`, using `"api_token_secret": "replace-with-32-or-more-random-characters"` and `"admin_password": "replace-with-a-strong-admin-password"`. Ignore `frontend/node_modules/`, `frontend/dist/`, `*.db`, and `*.db-*` in `.gitignore`.

- [ ] **Step 8: Run focused tests and commit**

Run: `python3 -m pytest tests/test_config.py tests/test_api_state.py -q`  
Expected: all tests PASS.

```bash
git add src/config.py src/api_state.py tests/test_config.py tests/test_api_state.py config.example.json requirements.txt .gitignore
git commit -m "feat: add API configuration and state store"
```

---

### Task 2: Address tokens and active-domain service

**Files:**
- Create: `src/api_auth.py`
- Modify: `src/domain_cache.py`
- Test: `tests/test_api_auth.py`
- Test: `tests/test_domain_cache.py`

**Interfaces:**
- Consumes: `StateStore.get_settings()`, `StateStore.get_frozen_domains()`
- Produces: `normalize_address(address, domains, settings) -> str`
- Produces: `AddressToken(secret).issue(address) -> str`
- Produces: `AddressToken(secret).read(token) -> str`
- Produces: `active_domains(cache_file, state) -> list[str]`

- [ ] **Step 1: Write failing token/domain tests**

Create `tests/test_api_auth.py`:

```python
import pytest
from src.api_auth import AddressToken, AddressValidationError, active_domains, normalize_address
from src.api_state import StateStore


def test_address_token_round_trip_and_tamper_rejection():
    signer = AddressToken("s" * 32)
    token = signer.issue("User@Example.com")
    assert signer.read(token) == "user@example.com"
    with pytest.raises(ValueError):
        signer.read(token + "x")


def test_normalize_address_applies_whitelist_and_forbidden_ids():
    settings = {"local_part_min": 3, "local_part_max": 32, "forbidden_ids": ["admin"]}
    assert normalize_address("User@Example.com", ["example.com"], settings) == "user@example.com"
    with pytest.raises(AddressValidationError):
        normalize_address("admin@example.com", ["example.com"], settings)
    with pytest.raises(AddressValidationError):
        normalize_address("user@other.com", ["example.com"], settings)


def test_auto_sync_uses_cache_and_off_uses_frozen_domains(tmp_path):
    cache = tmp_path / "domains.json"
    cache.write_text('["live.example"]')
    state = StateStore(str(tmp_path / "state.db"))
    assert active_domains(str(cache), state) == ["live.example"]
    state.replace_frozen_domains(["frozen.example"])
    state.update_settings({"auto_sync_domains": False})
    assert active_domains(str(cache), state) == ["frozen.example"]
```

- [ ] **Step 2: Run the tests and confirm failure**

Run: `python3 -m pytest tests/test_api_auth.py -q`  
Expected: FAIL with `ModuleNotFoundError: src.api_auth`.

- [ ] **Step 3: Implement passwordless HMAC tokens and validation**

Create `src/api_auth.py` using `base64.urlsafe_b64encode`, `hashlib.sha256`, `hmac.new`, `hmac.compare_digest`, and `json`. Token payload is exactly `{"address": normalized_address, "v": 1}`. Reject tokens with the wrong segment count, invalid base64/JSON, version other than `1`, or invalid signature.

Use this local-part pattern and normalize the domain with IDNA:

```python
_LOCAL_PART = re.compile(r"^[a-z0-9][a-z0-9._+-]*[a-z0-9]$|^[a-z0-9]$")
```

`active_domains()` reads `domains.json` through `DomainCache`, sorts/deduplicates valid domains when auto-sync is on, and returns the SQLite frozen set when it is off.

- [ ] **Step 4: Add safe domain snapshots**

Add to `DomainCache`:

```python
def domains(self) -> list[str]:
    with self._lock:
        return sorted(self._domains)

def replace(self, domains: list[str]) -> None:
    with self._lock:
        self._domains = set(domains)
        self._persist()
```

Add assertions for sorted copies and replacement to `tests/test_domain_cache.py`.

- [ ] **Step 5: Run focused tests and commit**

Run: `python3 -m pytest tests/test_api_auth.py tests/test_domain_cache.py -q`  
Expected: all tests PASS.

```bash
git add src/api_auth.py src/domain_cache.py tests/test_api_auth.py tests/test_domain_cache.py
git commit -m "feat: add stateless address tokens"
```

---

### Task 3: Stalwart JMAP mail operations

**Files:**
- Modify: `src/jmap_client.py`
- Test: `tests/test_jmap_mail.py`
- Modify: `tests/test_jmap_client.py`

**Interfaces:**
- Produces: `JmapClient.discover_mail_account_id() -> str`
- Produces: `JmapClient.list_messages(account_id, address, limit, position) -> tuple[int, list[dict]]`
- Produces: `JmapClient.get_message(account_id, message_id) -> dict | None`
- Produces: `JmapClient.set_seen(account_id, message_id, seen) -> bool`
- Produces: `JmapClient.delete_message(account_id, message_id) -> bool`
- Produces: `JmapClient.download_blob(account_id, blob_id, name) -> tuple[bytes, str]`
- Produces: `JmapClient.message_counts(account_id) -> dict[str, int]`

- [ ] **Step 1: Write failing JMAP mail tests**

Create `tests/test_jmap_mail.py` with mocked `httpx` responses that assert:

```python
def test_list_messages_queries_recipient_and_returns_query_total(client, mocked_post):
    mocked_post.return_value = response({"methodResponses": [
        ["Email/query", {"ids": ["m1"], "total": 1}, "q"],
        ["Email/get", {"list": [{"id": "m1", "subject": "Code", "to": [{"email": "box@example.com"}]}]}, "g"],
    ]})
    total, messages = client.list_messages("mail-account", "box@example.com", 15, 0)
    assert total == 1
    assert messages[0]["id"] == "m1"
    query = mocked_post.call_args.kwargs["json"]["methodCalls"][0][1]
    assert query["filter"]["operator"] == "OR"


def test_get_set_delete_and_blob_use_mail_account(client, mocked_post):
    mocked_post.side_effect = [
        response({"methodResponses": [["Email/get", {"list": [{"id": "m1", "blobId": "b1"}]}, "0"]]}),
        response({"methodResponses": [["Email/set", {"updated": {"m1": None}}, "0"]]}),
        response({"methodResponses": [["Email/set", {"destroyed": ["m1"]}, "0"]]}),
        blob_response(b"raw", "message/rfc822"),
    ]
    assert client.get_message("mail-account", "m1")["blobId"] == "b1"
    assert client.set_seen("mail-account", "m1", True)
    assert client.delete_message("mail-account", "m1")
    assert client.download_blob("mail-account", "b1", "message.eml") == (b"raw", "message/rfc822")
```

Define `client`, `mocked_post`, `response`, and `blob_response` in that file with `pytest` fixtures and `MagicMock`. Also test session discovery, text/html body values, attachments, JMAP method errors, and today/7-day/total query counts.

- [ ] **Step 2: Run JMAP tests and confirm failure**

Run: `python3 -m pytest tests/test_jmap_mail.py -q`  
Expected: FAIL because the mail methods do not exist.

- [ ] **Step 3: Refactor the client to reuse one request helper**

Keep the existing constructor and domain behavior. Add an instance `httpx.Client` only when supplied for tests; otherwise use `httpx`. Add:

```python
_MAIL_USING = ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"]

def _call(self, method_calls: list, using: list[str]) -> list:
    response = httpx.post(
        self._url,
        json={"using": using, "methodCalls": method_calls},
        headers=self._headers,
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("methodResponses", [])
```

`list_messages()` sends `Email/query` followed by a result-referenced `Email/get`. Its OR filter contains `{"to": address}` and `{"header": ["Delivered-To", address]}`. Summary properties are `id`, `blobId`, `threadId`, `from`, `to`, `subject`, `preview`, `keywords`, `hasAttachment`, `size`, and `receivedAt`.

`get_message()` requests those fields plus `cc`, `bcc`, `bodyValues`, `textBody`, `htmlBody`, `attachments`, `bodyStructure`, and `header:Delivered-To:asAddresses`.

`set_seen()` updates `keywords/$seen`; `delete_message()` uses `destroy`; `download_blob()` calls the JMAP download URL discovered from the session; `message_counts()` performs three `Email/query` calls with `calculateTotal: true` for all stored mail, UTC today, and the last seven days.

- [ ] **Step 4: Run all JMAP tests and commit**

Run: `python3 -m pytest tests/test_jmap_client.py tests/test_jmap_mail.py -q`  
Expected: all tests PASS, including unchanged domain provisioning.

```bash
git add src/jmap_client.py tests/test_jmap_client.py tests/test_jmap_mail.py
git commit -m "feat: add JMAP mailbox operations"
```

---

### Task 4: Mail.tm-shaped public API and Swagger

**Files:**
- Create: `src/api_models.py`
- Create: `src/api_server.py`
- Test: `tests/test_public_api.py`

**Interfaces:**
- Consumes: `ConfigStore`, `StateStore`, `AddressToken`, `active_domains`, and JMAP mail methods
- Produces: `create_app(config_path: str) -> FastAPI`
- Produces: public routes including `/site` and generated `/docs`, `/redoc`, `/openapi.json`

- [ ] **Step 1: Write failing API contract tests**

Create `tests/test_public_api.py` around `TestClient(create_app(config_path))` with a dependency-injected fake JMAP client. Cover these exact assertions:

```python
def test_domains_are_a_hydra_collection(client):
    response = client.get("/domains")
    assert response.status_code == 200
    body = response.json()
    assert body["@type"] == "hydra:Collection"
    assert body["hydra:member"][0]["domain"] == "example.com"


def test_passwordless_token_and_me(client):
    token_response = client.post("/token", json={"address": "box@example.com"})
    assert token_response.status_code == 200
    token = token_response.json()["token"]
    me = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["address"] == "box@example.com"


def test_site_exposes_only_public_settings(client):
    body = client.get("/site").json()
    assert body["appName"] == "Temporary Inbox"
    assert body["fetchSeconds"] == 20
    assert "jmapToken" not in body
    assert "adminPassword" not in body


def test_messages_require_bearer_and_return_hydra(client, bearer):
    assert client.get("/messages").status_code == 401
    response = client.get("/messages", headers=bearer)
    assert response.json()["@id"] == "/messages"


def test_message_id_cannot_cross_recipient(client, bearer, fake_jmap):
    fake_jmap.get_message.return_value = {
        "id": "m1",
        "to": [{"email": "other@example.com"}],
        "header:Delivered-To:asAddresses": [],
    }
    assert client.get("/messages/m1", headers=bearer).status_code == 404
```

Also test account validation without persistence, pagination, seen PATCH, delete, attachment/source streaming, blocked sender masking, error shapes, and whitelist rejection.

- [ ] **Step 2: Run public API tests and confirm failure**

Run: `python3 -m pytest tests/test_public_api.py -q`  
Expected: FAIL because API models and app factory do not exist.

- [ ] **Step 3: Define typed API models**

Create `src/api_models.py` with Pydantic models using aliases for JSON-LD keys. Define `AddressRequest`, `TokenResponse`, `AccountResource`, `DomainResource`, `SiteResource`, `EmailAddress`, `AttachmentResource`, `MessageSummary`, `MessageResource`, `SeenPatch`, `HydraDomains`, `HydraMessages`, and `HydraError`.

Use `ConfigDict(populate_by_name=True, extra="ignore")`. Every resource includes Mail.tm-compatible `@id`, `@type`, `id`, timestamps, and documented examples. `AddressRequest` contains only `address: str`.

- [ ] **Step 4: Implement the public application factory and routes**

Create `src/api_server.py` with:

```python
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
    register_public_routes(app)
    return app
```

Implement `bearer_address()` with `HTTPBearer(auto_error=False)`, `current_domains()` through `active_domains()`, `mail_account_id()` through configured override or JMAP session discovery, and `message_for_address()` that returns 404 unless normalized `to`, `cc`, `bcc`, or delivered-to addresses contain the bearer address.

Map JMAP summaries/details into the typed resources. Build HTML by following `htmlBody` part IDs into `bodyValues`, text by following `textBody`, and attachment links from blob IDs. Return `HydraError` consistently from exception handlers for validation, HTTP, and unexpected JMAP failures.

- [ ] **Step 5: Add security headers and request limits**

Add middleware that sets `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, and a CSP allowing only same-origin app assets plus FastAPI's Swagger CDN on `/docs`. Add a process-local fixed-window limit for `/token` and `/admin/login` keyed by client IP.

- [ ] **Step 6: Verify API, Swagger schema, and commit**

Add assertions that `/openapi.json` contains `/token`, `/messages/{message_id}`, bearer security, and passwordless request examples.

Run: `python3 -m pytest tests/test_public_api.py -q`  
Expected: all tests PASS.

```bash
git add src/api_models.py src/api_server.py tests/test_public_api.py
git commit -m "feat: add Mail.tm-shaped public API"
```

---

### Task 5: Admin authentication, settings, sync, and metrics

**Files:**
- Create: `src/admin_api.py`
- Modify: `src/api_server.py`
- Modify: `src/policy_daemon.py`
- Test: `tests/test_admin_api.py`
- Modify: `tests/test_policy_daemon.py`

**Interfaces:**
- Consumes: `ConfigStore`, `StateStore`, `DomainCache`, `JmapClient`
- Produces: `/admin/api/login`, `/admin/api/logout`, `/admin/api/dashboard`, `/admin/api/settings`, `/admin/api/sync-domains`, and `/admin/api/test-mail`

- [ ] **Step 1: Write failing admin tests**

Create `tests/test_admin_api.py` with exact cases for:

```python
def test_admin_login_sets_http_only_cookie(client):
    response = client.post("/admin/api/login", json={"password": "admin-secret"})
    assert response.status_code == 200
    assert response.json()["csrfToken"]
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie


def test_settings_mask_secret_and_require_csrf(admin_client):
    response = admin_client.get("/admin/api/settings")
    assert response.json()["mailServer"]["jmapToken"] == "********"
    assert admin_client.put("/admin/api/settings", json={}).status_code == 403


def test_sync_now_replaces_cache_only_on_success(admin_client, fake_jmap, cache_file):
    fake_jmap.list_domains.return_value = ["new.example"]
    response = admin_client.post("/admin/api/sync-domains", headers=admin_client.csrf)
    assert response.status_code == 200
    assert json.loads(cache_file.read_text()) == ["new.example"]


def test_dashboard_combines_jmap_and_activity(admin_client, fake_jmap):
    fake_jmap.message_counts.return_value = {"stored": 12, "today": 3, "sevenDays": 8}
    body = admin_client.get("/admin/api/dashboard").json()
    assert body["messages"]["today"] == 3
    assert "domainsToday" in body["domains"]
```

Also test wrong password, expired session, logout, CSRF mismatch, setting bounds, secret preservation when the masked value is submitted, failed JMAP test, failed sync fallback, and HTML/ad setting round trips.

- [ ] **Step 2: Run admin tests and confirm failure**

Run: `python3 -m pytest tests/test_admin_api.py -q`  
Expected: FAIL because the admin router does not exist.

- [ ] **Step 3: Implement admin sessions and routes**

Create `src/admin_api.py`. Login uses `secrets.compare_digest`, creates separate random session and CSRF tokens, stores only `sha256(session_token)` with a 12-hour expiry, sets cookie `tmail_admin`, and returns `{ "csrfToken": value }`. State-changing routes require header `X-CSRF-Token` matching the stored session.

Settings endpoints map these sections exactly:

```python
SITE_KEYS = {
    "app_name", "logo_data_url", "favicon_data_url", "primary_color", "accent_color", "language",
    "cookie_enabled", "cookie_text", "auto_sync_domains", "fetch_seconds",
    "message_limit", "local_part_min", "local_part_max", "forbidden_ids",
    "blocked_sender_domains", "header_html", "footer_html", "content_css", "ad_slots",
}
MAIL_KEYS = {"jmap_url", "jmap_token", "catchall_address", "mail_account_id", "retention_days"}
```

Validate polling at 10–300 seconds, message limit at 1–100, local-part min/max at 1–64 with min no greater than max, domain/list entries normalized and unique, colors as six-digit hex, logo/favicon as image data URLs no larger than 1 MiB decoded, and HTML/CSS/ad values at a documented maximum length. Preserve the current token when the request submits an empty or masked token. After a mail-setting save, replace `request.app.state.jmap` with a client built from the newly persisted configuration.

`sync-domains` writes through `DomainCache.replace()` only after a non-empty successful Stalwart response, records success/failure, and updates the frozen snapshot when auto-sync is off. Dashboard merges `JmapClient.message_counts()`, domain count, `activity_summary()`, and `last_sync()`.

- [ ] **Step 4: Record successful provisioning without affecting SMTP**

In `src/policy_daemon.py`, initialize `ConfigStore`, `StateStore`, and a lock-protected `(config fingerprint, JmapClient)` pair. At the start of each policy request, call `ConfigStore.get()` and rebuild the JMAP client only when `(jmap_url, jmap_token, catchall_address)` changes. This hot reload must not rebind the daemon listen socket or replace the domain cache path.

Immediately after `_cache.add(domain)`, execute:

```python
try:
    _state.record_event("domain_provisioned", domain)
except Exception as exc:
    logger.warning("Metric write failed for %s: %s", domain, exc)
```

Update `tests/test_policy_daemon.py` to assert a successful provision records once, a changed config rebuilds the JMAP client, and a failing metric store does not change the existing SMTP response. Align stale assertions with the current daemon contract: known/provisioned domains return `action=OK`, MX mismatch returns `action=REJECT`, invalid recipients return `action=REJECT Invalid recipient`, and transient/JMAP failures defer.

- [ ] **Step 5: Register the admin router and verify**

Register `admin_api.router` from `create_app()` with app dependencies supplied through `request.app.state`. Ensure `/admin` itself remains reserved for the SPA.

Run: `python3 -m pytest tests/test_admin_api.py tests/test_policy_daemon.py -q`  
Expected: all tests PASS.

```bash
git add src/admin_api.py src/api_server.py src/policy_daemon.py tests/test_admin_api.py tests/test_policy_daemon.py
git commit -m "feat: add protected mail administration API"
```

---

### Task 6: Vue foundation, address creation, and deep links

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/package-lock.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/main.ts`
- Create: `frontend/src/vite-env.d.ts`
- Create: `frontend/src/App.vue`
- Create: `frontend/src/api.ts`
- Create: `frontend/src/route.ts`
- Create: `frontend/src/session.ts`
- Create: `frontend/src/types.ts`
- Create: `frontend/src/styles.css`
- Create: `frontend/src/components/AddressPanel.vue`
- Test: `frontend/src/tests/route.test.ts`

**Interfaces:**
- Produces: `parseRoute(pathname: string) -> AppRoute`
- Produces: `api.token(address)`, `api.domains()`, and typed mailbox/admin calls
- Produces: browser-local `AddressSession[]` management

- [ ] **Step 1: Scaffold the minimal Vue/Vite package**

Create a Vue/Vite package with scripts:

```json
{
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc --noEmit && vite build",
    "test": "vitest run"
  },
  "dependencies": {"vue": "^3.5.0"},
  "devDependencies": {
    "@vitejs/plugin-vue": "^6.0.0",
    "@vue/test-utils": "^2.4.0",
    "jsdom": "^26.0.0",
    "typescript": "^5.8.0",
    "vite": "^7.0.0",
    "vitest": "^3.0.0",
    "vue-tsc": "^3.0.0"
  }
}
```

Set Vite dev proxy `/domains`, `/accounts`, `/token`, `/me`, `/messages`, `/sources`, and `/admin/api` to `http://127.0.0.1:8000`. Use Vue plugin only.

Use `frontend/src/vite-env.d.ts` containing `/// <reference types="vite/client" />`; strict TypeScript with `noUncheckedIndexedAccess`; `@vitejs/plugin-vue`; output directory `dist`; and an `index.html` containing `<div id="app"></div>` plus `/src/main.ts` as the module entry.

- [ ] **Step 2: Write failing route tests**

Create `frontend/src/tests/route.test.ts`:

```typescript
import { describe, expect, it } from 'vitest'
import { parseRoute } from '../route'

describe('parseRoute', () => {
  it('reserves admin and API documentation paths', () => {
    expect(parseRoute('/admin')).toEqual({ name: 'admin' })
    expect(parseRoute('/docs')).toEqual({ name: 'reserved' })
    expect(parseRoute('/openapi.json')).toEqual({ name: 'reserved' })
  })

  it('decodes a one-segment address once', () => {
    expect(parseRoute('/box%40example.com')).toEqual({ name: 'address', address: 'box@example.com' })
    expect(parseRoute('/box@example.com')).toEqual({ name: 'address', address: 'box@example.com' })
  })

  it('rejects malformed and nested paths', () => {
    expect(parseRoute('/not-an-address')).toEqual({ name: 'home' })
    expect(parseRoute('/a/b@example.com')).toEqual({ name: 'home' })
  })
})
```

- [ ] **Step 3: Run route tests and confirm failure**

Run: `cd frontend && npm install && npm test -- src/tests/route.test.ts`  
Expected: FAIL because `route.ts` does not exist. Commit the generated lockfile.

- [ ] **Step 4: Implement typed routing, API, and browser sessions**

`route.ts` reserves `admin`, `api`, `docs`, `redoc`, `openapi.json`, `settings`, `assets`, and `favicon.ico`; it accepts only one decoded segment containing exactly one `@`.

`session.ts` stores `{address, token}` entries under `tmail.addresses`, deduplicates by normalized address, remembers the active address, and tolerates invalid JSON by returning an empty list.

`api.ts` exposes one `request<T>()` wrapper that sends bearer/admin CSRF headers, parses Hydra errors, and defines all public/admin methods from the spec, including `GET /site`. `types.ts` contains the exact response interfaces, including quoted JSON-LD keys.

- [ ] **Step 5: Implement the address screen and direct-link handoff**

`App.vue` branches only among home/address, inbox, and admin route state. On an address deep link it calls `POST /token`, saves the session, and shows the inbox. `AddressPanel.vue` loads domains, accepts a custom local part, generates a six-character consonant/vowel random name, and calls the same token handoff. It includes copy, remembered-address switching, loading, empty-domain, and Hydra error states.

Use semantic form controls, explicit labels, visible focus rings, and `aria-live` for errors. Do not add a router or state package.

- [ ] **Step 6: Add the visual foundation and verify**

Implement CSS variables for off-white, charcoal, indigo, green, and red; a rigid desktop grid; mobile stacking below 800px; 1px borders; minimal shadows; and reduced-motion handling. No gradients or glass effects.

Run: `cd frontend && npm test && npm run build`  
Expected: route tests PASS and production build succeeds.

```bash
git add frontend
git commit -m "feat: add Vue address and deep-link flow"
```

---

### Task 7: Inbox, reader, attachments, and sandboxing

**Files:**
- Create: `frontend/src/components/InboxView.vue`
- Create: `frontend/src/components/MessageReader.vue`
- Create: `frontend/src/components/SandboxFrame.vue`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/styles.css`
- Test: `frontend/src/tests/SandboxFrame.test.ts`

**Interfaces:**
- Consumes: bearer session and typed message APIs
- Produces: polling message list, on-demand reader, safe HTML/content frame, downloads, seen/delete actions

- [ ] **Step 1: Write the failing sandbox test**

Create `frontend/src/tests/SandboxFrame.test.ts`:

```typescript
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SandboxFrame from '../components/SandboxFrame.vue'

describe('SandboxFrame', () => {
  it('isolates message HTML without scripts or same-origin access', () => {
    const wrapper = mount(SandboxFrame, { props: { html: '<p>Hello</p>', mode: 'message' } })
    const frame = wrapper.get('iframe')
    expect(frame.attributes('sandbox')).toBe('allow-popups allow-popups-to-escape-sandbox')
    expect(frame.attributes('srcdoc')).toContain('<p>Hello</p>')
  })

  it('allows scripts for ad content without same-origin access', () => {
    const wrapper = mount(SandboxFrame, { props: { html: '<script>void 0</script>', mode: 'content' } })
    expect(wrapper.get('iframe').attributes('sandbox')).toContain('allow-scripts')
    expect(wrapper.get('iframe').attributes('sandbox')).not.toContain('allow-same-origin')
  })
})
```

- [ ] **Step 2: Run the sandbox test and confirm failure**

Run: `cd frontend && npm test -- src/tests/SandboxFrame.test.ts`  
Expected: FAIL because `SandboxFrame.vue` does not exist.

- [ ] **Step 3: Implement the sandbox frame**

Create `SandboxFrame.vue` with `html` and `mode` props, a computed sandbox value exactly matching the tests, a descriptive title, and no `v-html`. Wrap configurable HTML with stored CSS inside `srcdoc`; keep email HTML unchanged except for a minimal `<base target="_blank">` prefix.

Render the `/site` header, footer, and configured ad slots from `App.vue` through `SandboxFrame mode="content"`; never place those strings directly in the Vue DOM.

- [ ] **Step 4: Implement the inbox and message reader**

`InboxView.vue`:

- polls `GET /messages?page=N` at the admin-configured interval returned by the public settings payload;
- pauses while the page is hidden and refreshes immediately on visibility return;
- preserves the selected ID across refresh if it still exists;
- requests browser notification permission only from an explicit user action;
- renders loading, empty, failure, unread, attachment, pagination, and refresh states.

`MessageReader.vue`:

- fetches full detail only after selection;
- PATCHes `seen: true` after a successful read;
- renders sender, recipients, subject, timestamp, safe HTML/text, and attachment links;
- confirms delete, then DELETEs and clears selection;
- downloads `/sources/{id}` as `.eml`;
- handles stale/deleted messages without breaking the list.

- [ ] **Step 5: Verify the inbox and commit**

Run: `cd frontend && npm test && npm run build`  
Expected: all frontend tests PASS and build succeeds.

```bash
git add frontend/src
git commit -m "feat: add temporary inbox and message reader"
```

---

### Task 8: Administration frontend

**Files:**
- Create: `frontend/src/admin/AdminApp.vue`
- Create: `frontend/src/admin/DashboardTab.vue`
- Create: `frontend/src/admin/GeneralTab.vue`
- Create: `frontend/src/admin/MailServerTab.vue`
- Create: `frontend/src/admin/DomainsTab.vue`
- Create: `frontend/src/admin/ContentTab.vue`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Consumes: all `/admin/api` endpoints from Task 5
- Produces: password login, mail dashboard, and four settings tabs

- [ ] **Step 1: Implement admin login and navigation**

`AdminApp.vue` shows a password form until `/admin/api/settings` succeeds, never persists the password, keeps the CSRF token only in memory, and provides tabs in this order: Dashboard, General, Mail Server, Domains & Inbox, HTML & Ads. Logout clears the cookie server-side and in-memory CSRF state.

- [ ] **Step 2: Implement the mail-activity dashboard**

`DashboardTab.vue` renders:

- active domain count;
- stored, today, and seven-day message counts;
- today and seven-day provision counts;
- recent provisioned domains with timestamps;
- auto-sync state, last successful sync, and last error.

Use text/table markup, loading skeletons, and a manual refresh button. Do not add charts or host metrics.

- [ ] **Step 3: Implement General and Mail Server settings**

`GeneralTab.vue` edits app name, logo/favicon uploads, colors, language, and cookie notice. Logo/favicon files are validated as images no larger than 1 MiB and converted with `FileReader.readAsDataURL()` before save. `MailServerTab.vue` edits JMAP URL, masked token, catch-all address, optional account ID, and retention days; it has **Test connection** and does not replace the saved token when the masked value is unchanged.

Each form keeps its own draft, validates before submit, disables save while pending, and shows an `aria-live` saved/error message.

- [ ] **Step 4: Implement Domains & Inbox settings**

`DomainsTab.vue` includes auto-sync toggle, active whitelist readout, last sync/error, **Sync now**, polling seconds, message limit, local-part bounds, forbidden IDs, and blocked sender domains. Turning sync off confirms that the current whitelist will freeze. Manual sync refreshes the displayed whitelist only after success.

- [ ] **Step 5: Implement sandboxed HTML & Ads settings**

`ContentTab.vue` edits header/footer HTML, content-block CSS, and named ad slots with side-by-side `SandboxFrame mode="content"` previews. Do not include global JavaScript. Label that scripts in ad HTML run in an isolated origin and cannot access inbox storage.

- [ ] **Step 6: Verify admin UI and commit**

Run: `cd frontend && npm test && npm run build`  
Expected: all tests PASS and the complete admin build type-checks.

```bash
git add frontend/src
git commit -m "feat: add mail administration frontend"
```

---

### Task 9: Static serving, services, installation, and final verification

**Files:**
- Modify: `src/api_server.py`
- Create: `tests/test_api_static.py`
- Create: `deploy/tmail-api.service`
- Modify: `deploy/install.sh`
- Modify: `deploy/deploy.sh`
- Modify: `README.md`

**Interfaces:**
- Consumes: `frontend/dist` and `create_app()`
- Produces: SPA/static serving, API systemd service, repeatable build/deploy instructions

- [ ] **Step 1: Write failing static-routing tests**

Create `tests/test_api_static.py`:

```python
def test_spa_serves_home_admin_and_address_routes(client, frontend_dist):
    for path in ["/", "/admin", "/box@example.com"]:
        response = client.get(path)
        assert response.status_code == 200
        assert "<div id=\"app\"></div>" in response.text


def test_api_and_docs_are_not_shadowed_by_spa(client):
    assert client.get("/domains").headers["content-type"].startswith("application/ld+json")
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200
```

- [ ] **Step 2: Run static tests and confirm failure**

Run: `python3 -m pytest tests/test_api_static.py -q`  
Expected: FAIL because the frontend distribution is not mounted.

- [ ] **Step 3: Serve immutable assets and explicit SPA fallbacks**

After all API/admin/docs routes are registered, mount `/assets` with `StaticFiles`. Add explicit `/`, `/admin`, and `/{address}` handlers returning `index.html`; the address handler rejects reserved names before returning the SPA. Return 503 with a plain installation message when `index.html` is absent rather than hiding API startup failure.

Add `main()` to load `TMAIL_CONFIG` and run Uvicorn on configured API address/port. Keep the app factory import-safe for tests.

- [ ] **Step 4: Add and wire the API service**

Create `deploy/tmail-api.service`:

```ini
[Unit]
Description=Tmail Web API and Frontend
After=network.target tmail-policy.service

[Service]
User=tmail-policy
WorkingDirectory=/opt/tmail-policy
Environment=TMAIL_CONFIG=/opt/tmail-policy/config.json
ExecStart=/usr/bin/python3 -m src.api_server
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Update both deployment scripts to build `frontend/`, copy all new Python modules plus `frontend/dist`, install the service, preserve an existing production `config.json`, validate that it contains a 32-character `api_token_secret` and non-empty `admin_password` before enabling `tmail-api`, set ownership, and restart `tmail-api` after `tmail-policy`. Print exact `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'` guidance when the token secret is missing. Do not automatically configure TLS or overwrite an existing reverse proxy.

- [ ] **Step 5: Document local and production operation**

Update `README.md` with:

- Node 20+ and Python requirements;
- config generation for `api_token_secret` and admin password;
- `python3 -m src.api_server` and `npm run dev` local commands;
- `npm run build` production command;
- systemd status/log commands for `tmail-api`;
- reverse proxy target `127.0.0.1:8000` and HTTPS requirement;
- public `/docs`, `/redoc`, `/openapi.json` locations;
- passwordless `/token` example and bearer `/messages` example;
- direct `https://host/user@example.com` behavior;
- domain auto-sync on/off semantics.

- [ ] **Step 6: Run complete verification**

Run:

```bash
python3 -m pytest -q
cd frontend && npm test && npm run build
```

Expected: all Python and frontend tests PASS; Vue type-check and Vite production build succeed.

Run: `git diff --check`  
Expected: no output.

- [ ] **Step 7: Commit the integrated service**

```bash
git add src/api_server.py tests/test_api_static.py deploy/tmail-api.service deploy/install.sh deploy/deploy.sh README.md
git commit -m "feat: deploy temporary mail web service"
```
