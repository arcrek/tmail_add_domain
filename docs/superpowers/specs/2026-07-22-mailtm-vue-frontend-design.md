# Vue Temporary-Mail Frontend and Mail.tm-Shaped API

**Date:** 2026-07-22  
**Status:** Approved for planning

## Goal

Add a Vue 3 + TypeScript + Vite frontend to the existing Stalwart domain-provisioning repository. The frontend keeps the public temporary-mail workflow of `tmail_frontend_demo`, reads mail through Stalwart JMAP, automatically exposes newly provisioned domains, and uses Mail.tm-style routes and Hydra response objects.

The service remains passwordless for temporary-mail users. Admin settings alone require authentication.

## Existing System

The current Python service sits in the SMTP path:

```text
Postfix -> policy daemon -> MX validation -> Stalwart domain provisioning
                                      \-> shared domains.json cache
```

The demo provides the product workflow to preserve:

- create a custom or random address from an allowed domain;
- keep and switch between addresses in the browser;
- poll an inbox and notify on new messages;
- open HTML or text messages;
- download attachments or the message as `.eml`;
- delete messages;
- open an address directly from a URL;
- configure branding, mail access, domains, limits, and HTML/ad content.

The demo's implementation is not reused. Its Laravel, Livewire, IMAP, and compiled frontend are references only.

## Architecture

```text
Browser
  |  Vue 3 SPA
  v
FastAPI service
  |-- Mail.tm-shaped public API
  |-- password-protected admin API
  |-- compiled Vite assets
  |-- SQLite settings and activity events
  v
Stalwart JMAP

Postfix -> existing policy daemon -> Stalwart domain provisioning
                    |
                    +-> domains.json + best-effort activity event
```

The existing policy daemon remains responsible for MX validation and first-mail domain provisioning. The new API service does not duplicate that SMTP logic.

The FastAPI service and policy daemon reuse `JmapClient`. The Stalwart bearer token stays server-side. SQLite stores site settings, the frozen domain whitelist used when automatic sync is off, admin sessions, and mail activity events. It does not store temporary-user accounts, user passwords, user tokens, or messages.

FastAPI serves the compiled Vue application from the same origin as the API. This avoids browser CORS configuration and keeps administration cookies same-origin.

## Domain Synchronization

`domains.json`, already updated immediately after successful policy-daemon provisioning, is the normal frontend whitelist source.

- With **Auto-sync Stalwart domains** on, `GET /domains` reloads the small shared JSON file and exposes every valid domain in it immediately.
- Turning auto-sync off copies the current domains into SQLite and freezes that whitelist.
- Turning it back on resumes the shared-cache source.
- **Sync now** calls Stalwart `x:Domain/get`, refreshes `domains.json`, and reports the result.
- A failed refresh never replaces the last valid whitelist with an empty list.

Only addresses whose normalized domain is in the active whitelist can receive an API token or access messages.

## Public API

The API follows the resource names and JSON shapes documented by Mail.tm at <https://api.mail.tm/docs.jsonld>. It intentionally differs from Mail.tm authentication: this public service has no stored accounts or passwords.

### Resources

```text
GET    /domains
GET    /domains/{id}
POST   /accounts
POST   /token
GET    /me
GET    /messages
GET    /messages/{id}
PATCH  /messages/{id}
DELETE /messages/{id}
GET    /messages/{id}/attachments/{blob_id}
GET    /sources/{id}
```

### Interactive API Documentation

FastAPI's built-in OpenAPI support exposes:

- `GET /docs` — interactive Swagger UI;
- `GET /openapi.json` — machine-readable OpenAPI schema;
- `GET /redoc` — read-only ReDoc reference.

The schema documents the Mail.tm-shaped resources, Hydra responses, passwordless `POST /token` input, bearer-token usage, pagination, validation errors, and the intentional differences from Mail.tm authentication. Example requests and responses are defined on the FastAPI models so the documentation stays generated from the implemented contract rather than a separate handwritten copy.

Collections use Mail.tm's Hydra envelope:

```json
{
  "@context": "/contexts/Message",
  "@id": "/messages",
  "@type": "hydra:Collection",
  "hydra:totalItems": 1,
  "hydra:member": []
}
```

Domain and message objects use stable opaque IDs and Mail.tm field names where the corresponding Stalwart data exists.

### Passwordless Address Tokens

`POST /accounts` accepts `{ "address": "user@example.com" }`, validates the local part and active domain, and returns a stateless Account-shaped resource. It stores nothing. This endpoint exists for Mail.tm client flow compatibility.

`POST /token` accepts the same address and returns:

```json
{
  "id": "stable-address-id",
  "token": "signed-address-token"
}
```

The token is an opaque, standard-library HMAC signature over the normalized address. It requires no database record and can always be reissued. The signing secret lives in the protected server configuration.

All mailbox routes require `Authorization: Bearer <token>`. There is no `?address=` mailbox API. Anyone may request a token for any valid whitelisted address; the token is address scoping, not private-mail authentication.

`GET /me` returns the Account-shaped resource derived from the token.

### Messages

`GET /messages` queries the shared Stalwart catch-all account for the token's recipient and returns lightweight summaries: sender, recipients, subject, intro, seen state, attachment flag, size, and timestamps.

`GET /messages/{id}` performs a separate JMAP read and returns the selected message's text body, HTML body, attachment metadata, and source/download links. Message bodies are not included in the collection response.

Every read, patch, delete, attachment, and source operation rechecks that the message belongs to the token address. A guessed message ID cannot cross recipient scope.

`PATCH /messages/{id}` supports Mail.tm's `seen` update. `DELETE /messages/{id}` deletes the Stalwart message. `GET /sources/{id}` downloads the original RFC 822/MIME source for `.eml` use. Attachments stream from Stalwart and are not copied into a public directory.

## Frontend

### Stack

- Vue 3 Composition API
- TypeScript
- Vite
- browser `fetch`, Clipboard API, Notifications API, and local storage
- no Pinia, UI framework, or client-side data library

The frontend uses a small typed API module and component-local state. The generated mockup establishes the visual direction: warm off-white surfaces, charcoal typography, restrained indigo accents, flat borders, and a desktop three-column inbox that stacks cleanly on mobile.

### Public Workflow

The address screen loads `GET /domains`, then lets the user enter a valid local part or generate a random one. It calls `POST /token`, stores the current address/token in local storage, and opens the inbox. Multiple locally remembered addresses can be switched or removed without server-side account records.

The inbox polls at the configured interval, shows summaries, and fetches the full message only when selected. It supports copy, refresh, new address, seen state, delete, attachments, raw `.eml` download, empty/loading/error states, and browser notifications after permission is granted.

Untrusted message HTML renders in a sandboxed iframe. External navigation opens in a new tab without opener access. The application never injects email HTML into the Vue document.

### Direct Address URLs

Visiting this route performs a passwordless inbox handoff:

```text
https://frontend.example/user@example.com
```

The app normalizes and validates the address, requests a token, stores it locally, and opens the inbox without another action. Invalid local parts or disabled domains return to the address screen with a clear error.

Static reserved routes such as `/admin`, `/api`, `/docs`, `/redoc`, `/openapi.json`, `/settings`, and asset paths take priority over the one-segment address route. The address is URL-decoded once and must contain exactly one `@`.

## Administration

The admin login uses a single password from protected server configuration. A successful login creates a short-lived HttpOnly, Secure, SameSite=Strict session cookie. Mutating requests also require a CSRF header. Login attempts are rate-limited.

### Dashboard

The Dashboard shows mail activity only:

- active/synced domain count;
- messages currently stored;
- messages received today and during the last seven days;
- domains provisioned today and during the last seven days;
- recent domain provisions;
- auto-sync state, last successful sync, and last sync error.

Message counts come from live JMAP queries when the admin loads the dashboard. Domain-provision events are written best-effort to SQLite after successful provisioning; metrics failure must never affect SMTP acceptance. No host CPU, memory, disk, or temporary-account metric is included.

### General

- application name;
- logo and favicon;
- primary/accent colors;
- default language;
- cookie notice enable/text.

### Mail Server

- Stalwart JMAP URL;
- server-side bearer token, always masked after save;
- catch-all address;
- mail account ID override, with automatic JMAP session discovery by default;
- **Test connection** for domain listing and mailbox query.

Changes are validated and written atomically to the protected configuration. Services reload changed configuration without exposing secrets to the browser.

### Domains & Inbox

- automatic domain sync toggle;
- active whitelist and sync status;
- **Sync now** action;
- inbox polling interval;
- message page limit;
- retention days;
- custom local-part minimum and maximum length;
- forbidden local parts;
- blocked sender domains.

### HTML & Ads

- header HTML;
- footer HTML;
- custom CSS for those content blocks;
- named ad/content slots.

Custom HTML and ad code run in sandboxed frames isolated from the Vue application's origin and local storage. Arbitrary global JavaScript is intentionally excluded because it could read public mailbox tokens or replace application behavior.

## Validation and Error Handling

- Normalize domains and addresses to lowercase before comparison.
- Reject malformed addresses, invalid local-part lengths, forbidden IDs, and non-whitelisted domains with a Mail.tm/Hydra-style `422` error.
- Return `401` for missing, malformed, or invalid signatures.
- Return `404` when a message does not exist or does not belong to the token address.
- Map Stalwart timeouts and invalid responses to `502` without leaking bearer tokens or internal response bodies.
- Preserve the last valid domain whitelist when Stalwart or the cache is unavailable.
- Stream attachments with safe filenames and explicit content types.
- Use constant-time HMAC comparison.
- Never log admin passwords, Stalwart tokens, address tokens, or message bodies.

## Persistence

SQLite contains only:

- mutable site settings;
- the frozen whitelist used while auto-sync is disabled;
- hashed/expiring admin session identifiers;
- domain provisioning and sync activity events.

Temporary addresses and address tokens are browser-local/stateless. Messages and attachments remain in Stalwart. Existing retention cleanup remains the source of truth for message deletion by age.

## Verification

Backend tests cover:

- Mail.tm/Hydra domain, account, token, message, and error shapes;
- generated OpenAPI paths, auth declarations, and examples;
- HMAC token creation, parsing, tamper rejection, and address normalization;
- recipient isolation for message read, patch, delete, attachment, and source routes;
- JMAP summary/detail mapping;
- domain sync on/off, manual refresh, and failure fallback;
- admin login, CSRF checks, secret masking, and settings validation;
- activity metrics without affecting policy-daemon decisions.

Frontend checks cover:

- TypeScript and production Vite build;
- address parsing and reserved-route behavior;
- direct-address token handoff;
- inbox list/detail state and API errors;
- sandbox attributes for message and configurable HTML frames.

The final verification includes the existing Python test suite, the new API tests, Vue type checking, and a production Vite build.

## Explicit Non-Goals

- Creating one Stalwart mailbox per temporary address
- Storing temporary-user accounts or passwords
- Private inbox authentication
- Direct address query parameters on mailbox routes
- Replacing the Postfix policy-daemon flow
- Host infrastructure monitoring
- Arbitrary global JavaScript injection
- Reusing or maintaining the Laravel demo
