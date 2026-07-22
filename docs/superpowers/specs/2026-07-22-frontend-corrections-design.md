# Frontend Corrections

**Date:** 2026-07-22  
**Status:** Awaiting written-spec review

## Goal

Correct three gaps in the temporary-mail application:

1. automatically discover Stalwart domains while automatic sync is enabled;
2. make the public and admin interfaces match the approved three-column mail-client reference;
3. preserve legitimate email HTML styling without allowing email scripts or forms.

The existing Vue, TypeScript, Vite, FastAPI, JMAP, SQLite, and stateless address-token architecture remains unchanged.

## Domain Synchronization

The current automatic mode only reads `domains.json`. It does not discover domains added directly to Stalwart.

When `auto_sync_domains` is enabled:

- `GET /domains` queries Stalwart using `x:Domain/get`, validates and normalizes the returned names, then atomically replaces `domains.json`;
- address validation retries that same refresh once when a syntactically valid domain is absent from the cache, covering direct-address URLs and API clients that do not load `/domains` first;
- a timeout, malformed response, or empty response preserves and serves the last valid cache;
- concurrent refreshes use the existing admin lock so a manual sync or mail-settings update cannot publish stale state.

When automatic sync is disabled, no public request contacts Stalwart for domains. The frozen SQLite whitelist remains authoritative, exactly as it does now. **Sync now** remains available to administrators and updates the frozen list after a successful explicit refresh.

This request-driven design gives users current domains on page load without introducing a background scheduler, polling interval, or multi-worker coordination.

## Interface

The supplied mockup is the visual source of truth for the whole application, including administration.

### Shared shell

Desktop uses three vertical regions with white surfaces and light gray dividers:

- a narrow navigation/account rail;
- a middle list or settings-navigation column;
- a wide content/detail column.

The visual system uses compact sans-serif typography, restrained blue actions and selection states, minimal rounding, no decorative shadows, and dense spacing. Mobile collapses the columns into sequential views with clear back navigation.

Only real application actions appear. The implementation will not add mockup-only features such as Sent mail. Existing accessibility states, keyboard focus, loading states, and inline errors remain.

### Public mail

The left rail contains branding, the active address, copy, refresh, new-address, inbox count, API status, and forget/sign-out. The middle column contains the inbox list and pagination. The right column contains message metadata, actions, body, and attachments.

Address creation uses the same shell: the address controls occupy the main content area, remembered inboxes remain available, and opening an address transitions into the three-column inbox without changing API behavior.

### Administration

Administration uses the same shell and visual tokens. Its left rail contains branding and logout; the middle column contains Dashboard, General, Mail Server, Domains & Inbox, and HTML & Ads; the right column contains the selected settings panel. Existing form behavior, CSRF protection, save locks, and session recovery do not change.

## Email HTML Rendering

The raw MIME and JMAP HTML both contain the expected inline styles. They are currently blocked because a `srcdoc` frame inherits the application's restrictive Content Security Policy.

Message HTML will use a dedicated sandbox document with its own response CSP:

- allow inline email styles and remote/data images;
- block forms, framing, plugins, navigation of the application, and all untrusted scripts;
- allow only the renderer bootstrap script through a fresh per-response nonce;
- keep the iframe on an opaque sandboxed origin;
- force links to open in a new tab without opener access;
- add only a small responsive baseline for viewport sizing, wrapping, images, and oversized tables.

The parent posts the HTML fragment into the renderer after load. The HTTP CSP remains active after document replacement, so scripts and event handlers embedded in the email cannot execute. Plain-text switching remains available.

Admin-configured HTML remains in its existing separate content sandbox because it has different trust and scripting requirements.

## Failure Behavior

- Domain refresh failure serves the previous valid whitelist and records no false success.
- An empty Stalwart domain result never clears the cache.
- A renderer load failure leaves the plain-text body accessible.
- Missing or invalid HTML continues to fall back to plain text.
- No JMAP token, admin session token, address token, or message body is logged.

## Verification

Backend regression tests will cover automatic refresh on `GET /domains`, refresh-on-miss for direct token issuance, frozen-mode isolation, and stale-cache fallback.

Frontend tests will cover the three-column public and admin structure, real navigation labels, responsive/back-state behavior, renderer URL and sandbox attributes, and plain-text fallback. Security tests will verify the dedicated renderer CSP allows styles/images while rejecting untrusted scripts and forms.

Final verification includes the complete Python suite, complete Vitest suite, Vue type checking, production Vite build, and live checks against `mail.tm-mails.com` for domain discovery and styled message rendering.

## Non-Goals

- Background domain polling or a new sync interval
- Sent mail, contacts, or other mockup-only features
- A UI framework or new state library
- Executing scripts from received email
- Changing the passwordless public mailbox model
