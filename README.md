# tmail-add-domain

Temporary-mail web app and API backed by Stalwart JMAP. Postfix asks the policy daemon to provision any recipient domain whose MX points at this server; the web app then exposes passwordless, address-scoped inboxes and an administrator console.

## Requirements

- Python 3.10+
- Node.js 20+ and npm
- Postfix
- Stalwart with JMAP enabled
- A Stalwart bearer token allowed to manage domains and read the catch-all mailbox

## Configuration

Copy `config.example.json` to `config.json`. Generate the API signing secret with exactly this command and store its output as `api_token_secret`:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Set `admin_password` to a strong, non-empty password. The API refuses to start unless the stripped signing secret contains at least 32 characters, the admin password is nonblank, and neither value is a shipped `replace-with...` placeholder. For local operation, also set `frontend_dist` to `frontend/dist` and use writable local paths for `cache_file` and `state_db`.

The main web settings are:

```json
{
  "api_listen_addr": "127.0.0.1",
  "api_listen_port": 8000,
  "api_token_secret": "generated-secret",
  "admin_password": "strong-password",
  "state_db": "/var/lib/tmail-policy/state.db",
  "frontend_dist": "/opt/tmail-policy/frontend/dist"
}
```

Keep `config.json` mode `0600`. Production services use the mutable runtime copy at `/var/lib/tmail-policy/config.json`; the release tree under `/opt/tmail-policy` stays root-owned and read-only to the service. The install and deploy scripts preserve an existing runtime config untouched. If the runtime copy is absent, they migrate the legacy `/opt/tmail-policy/config.json` or use the supplied config for a fresh installation. Legacy migration captures rollback state, stops the old API writer, takes and validates a final snapshot, then promotes the release.

## Local development

Install Python and frontend dependencies:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cd frontend
npm install
```

Run the API from the repository root:

```bash
TMAIL_CONFIG="$PWD/config.json" .venv/bin/python -m src.api_server
```

In another terminal, run the Vite development server:

```bash
cd frontend
npm run dev
```

Vite proxies API and admin requests to `127.0.0.1:8000`. Build the production SPA with:

```bash
cd frontend
npm ci
npm run build
```

The API serves the resulting `frontend/dist`; a missing build returns plain HTTP 503 for SPA routes while API and documentation routes remain available.

## Production installation

From a checkout containing `config.json`:

```bash
sudo bash deploy/install.sh
```

For a later remote deployment:

```bash
./deploy/deploy.sh root@example-host
```

Both scripts build and validate a root-owned staged snapshot, preserve an existing `/var/lib/tmail-policy/config.json` without overwriting it, promote only after dependency preparation succeeds, and restart `tmail-api` after `tmail-policy`. The service owns only its runtime directory and config, allowing atomic administrator updates without write access to release code, helpers, or units.

They do not configure TLS or modify an existing reverse proxy. Put nginx, Caddy, Apache, or another proxy in front of `127.0.0.1:8000`, serve the public site only over HTTPS, and forward the original host and client address. HTTPS is required because the administrator session cookie is `Secure`.

Service checks:

```bash
systemctl status tmail-policy
systemctl status tmail-api
journalctl -u tmail-api -f
```

## Web and API routes

Unlike Mail.tm, this service intentionally has no account/password registration or login. `POST /accounts` is stateless address-validation compatibility and stores no account; `POST /token` accepts only an active address and returns its scoped bearer token.

- `/` opens the address picker and inbox app.
- `/admin` opens the administrator console.
- `https://host/user@example.com` opens that address directly; the app requests a scoped bearer token after validating the address against the active domain whitelist.
- `/docs`, `/redoc`, and `/openapi.json` are public API documentation endpoints.
- `/assets/*` serves immutable production assets.

Issue a passwordless token for an active address:

```bash
curl -sS https://host/token \
  -H 'Content-Type: application/json' \
  -d '{"address":"user@example.com"}'
```

Copy the returned `token` value, then list only that address's messages:

```bash
TOKEN='returned-token'
curl -sS https://host/messages -H "Authorization: Bearer $TOKEN"
```

Tokens are stateless and scoped to one normalized address; no mailbox password or account row is created.

## Domain synchronization

With **Automatically sync domains** on (the default), the public whitelist follows the policy daemon's live domain cache. Domains whose MX points to this server appear after first-mail provisioning, and a manual **Sync domains** refresh replaces the cache from Stalwart.

Turning automatic sync off freezes the current whitelist so later cache changes do not alter public address availability. Manual **Sync domains** still replaces that frozen whitelist while automatic sync remains off. Re-enabling automatic sync resumes reading the live cache.

## Mail flow

```text
Postfix (:25) -> Policy daemon (:10030) -> DNS MX check -> Stalwart JMAP -> Stalwart SMTP (:2525)
```

Postfix must own port 25. Configure it to consult `inet:127.0.0.1:10030` as shown in `deploy/postfix_main_snippet.cf`; Stalwart receives the accepted relay on port 2525.
