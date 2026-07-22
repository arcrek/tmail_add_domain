# Frontend Corrections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make domain discovery automatic, align every application screen with the approved three-column mail-client reference, and render original email styling safely.

**Architecture:** Reuse the existing Stalwart sync and cache paths, refreshing on public domain reads and whitelist misses rather than adding a scheduler. Refactor the existing Vue templates and CSS in place into a shared three-pane visual system. Move received HTML from inherited-CSP `srcdoc` into a dedicated nonce-protected sandbox document.

**Tech Stack:** Python 3.14, FastAPI, JMAP, pytest, Vue 3 Composition API, TypeScript, Vite, Vitest, vanilla CSS

## Global Constraints

- Preserve the passwordless public mailbox and stateless address-token model.
- Never clear the last valid domain cache after an empty or failed Stalwart response.
- Automatic refresh must make no Stalwart domain request while `auto_sync_domains` is off.
- Never expose or log the Stalwart token, admin password/session, address token, or message body.
- Received email may use inline styles and remote/data images, but scripts, event handlers, forms, frames, plugins, and application-origin access remain blocked.
- Match the supplied white three-column mail-client reference across public and admin screens; do not add nonfunctional Sent, Contacts, or Addresses navigation.
- Keep Vue, TypeScript, Vite, and vanilla CSS; add no UI framework, router, state library, scheduler, or sanitizer dependency.
- Spec: `docs/superpowers/specs/2026-07-22-frontend-corrections-design.md`

---

## File Map

```text
src/admin_api.py                         shared Stalwart domain refresh operation
src/api_server.py                        public refresh triggers and message sandbox route/CSP
tests/test_admin_api.py                  shared/manual sync regression coverage
tests/test_public_api.py                 automatic refresh and renderer security coverage
frontend/src/App.vue                     removes the competing editorial header/footer shell
frontend/src/components/AddressPanel.vue three-pane address and remembered-inbox layout
frontend/src/components/InboxView.vue    three-pane account/list/reader layout
frontend/src/components/SandboxFrame.vue dedicated message renderer transport
frontend/src/admin/AdminApp.vue          three-pane admin layout
frontend/src/styles.css                  reference-matched visual system and responsive behavior
frontend/src/tests/address-flow.test.ts  address-shell assertions
frontend/src/tests/InboxView.test.ts     inbox-shell assertions
frontend/src/tests/SandboxFrame.test.ts  renderer transport assertions
frontend/src/tests/AdminApp.test.ts      admin-shell assertions
```

---

### Task 1: Request-driven Stalwart domain refresh

**Files:**
- Modify: `src/admin_api.py:267-306`
- Modify: `src/api_server.py:200-205,425-444`
- Test: `tests/test_admin_api.py`
- Test: `tests/test_public_api.py`

**Interfaces:**
- Produces: `refresh_domains(request: Request, *, require_auto: bool = False) -> list[str]`
- Consumes: `JmapClient.list_domains()`, `DomainCache.generation()`, `DomainCache.replace()`, `StateStore.record_sync()`
- Public `GET /domains` and `_address()` reuse that operation; the admin endpoint remains the explicit caller with `require_auto=False`.

- [ ] **Step 1: Add failing public-refresh tests**

Append to `tests/test_public_api.py`:

```python
def test_domains_refresh_from_stalwart_when_auto_sync_is_on(client, fake_jmap, config_path):
    fake_jmap.list_domains.return_value = ["example.com", "new.example"]

    response = client.get("/domains")

    assert response.status_code == 200
    assert [item["domain"] for item in response.json()["hydra:member"]] == [
        "example.com", "new.example",
    ]
    assert json.loads((config_path.parent / "domains.json").read_text()) == [
        "example.com", "new.example",
    ]


def test_token_refreshes_once_for_a_new_valid_domain(client, fake_jmap):
    fake_jmap.list_domains.return_value = ["example.com", "new.example"]

    response = client.post("/token", json={"address": "box@new.example"})

    assert response.status_code == 200
    fake_jmap.list_domains.assert_called_once_with()


def test_auto_refresh_failure_keeps_last_valid_domains(client, fake_jmap):
    fake_jmap.list_domains.side_effect = TimeoutError

    response = client.get("/domains")

    assert response.status_code == 200
    assert [item["domain"] for item in response.json()["hydra:member"]] == ["example.com"]


def test_frozen_domains_never_query_stalwart(client, fake_jmap):
    client.app.state.state_store.replace_frozen_domains(["frozen.example"])
    client.app.state.state_store.update_settings({"auto_sync_domains": False})

    response = client.get("/domains")

    assert response.status_code == 200
    assert response.json()["hydra:member"][0]["domain"] == "frozen.example"
    fake_jmap.list_domains.assert_not_called()
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
rtk .venv/bin/pytest tests/test_public_api.py -k "refresh_from_stalwart or refreshes_once or refresh_failure or frozen_domains" -vv
```

Expected: the first three tests fail because public routes do not call `list_domains`; frozen mode already passes.

- [ ] **Step 3: Extract the existing sync transaction**

In `src/admin_api.py`, move the body of `sync_domains()` into this shared function and make the endpoint call it:

```python
def refresh_domains(request: Request, *, require_auto: bool = False) -> list[str]:
    state = request.app.state.state_store
    if require_auto and not state.get_settings()["auto_sync_domains"]:
        return _active_domains(request)
    with request.app.state.admin_lock:
        jmap = request.app.state.jmap
    try:
        for _attempt in range(3):
            generation = request.app.state.domain_cache.generation()
            values = jmap.list_domains()
            if not values:
                raise ValueError("Stalwart returned no domains")
            domains = _list(values, "domains", _domain)
            if not domains:
                raise ValueError("Stalwart returned no valid domains")
            with request.app.state.admin_lock:
                if request.app.state.jmap is not jmap:
                    raise RuntimeError("JMAP client changed during sync")
                if require_auto and not state.get_settings()["auto_sync_domains"]:
                    return _active_domains(request)
                if not request.app.state.domain_cache.replace(
                    domains, expected_generation=generation
                ):
                    continue
                if not state.get_settings()["auto_sync_domains"]:
                    state.replace_frozen_domains(domains)
                state.record_sync(True, f"{len(domains)} domains")
                return domains
        raise RuntimeError("Domain cache changed during sync")
    except Exception as exc:
        state.record_sync(False, type(exc).__name__)
        raise


@router.post("/sync-domains")
def sync_domains(request: Request, _session_value: dict[str, object] = Depends(_csrf)):
    try:
        domains = refresh_domains(request)
    except Exception:
        raise HTTPException(502, "Domain sync failed") from None
    return {"domains": domains, "lastSync": request.app.state.state_store.last_sync()}
```

Keep the existing `_list()` and `_domain()` validation; do not duplicate normalization in `api_server.py`.

- [ ] **Step 4: Trigger refresh from public routes**

Import `refresh_domains` beside `admin_router` in `src/api_server.py`. Update `_address()` and `GET /domains`:

```python
def _address(request: Request, value: str, config: Config | None = None) -> str:
    domains = current_domains(request, config)
    try:
        raw_domain = value.rsplit("@", 1)[1] if value.count("@") == 1 else ""
        missing = _domain(raw_domain) not in domains
    except AddressValidationError:
        missing = False
    if missing and request.app.state.state_store.get_settings()["auto_sync_domains"]:
        try:
            refresh_domains(request, require_auto=True)
        except Exception:
            pass
        domains = current_domains(request, config)
    return normalize_address(value, domains, request.app.state.state_store.get_settings())
```

At the start of `domains()` add:

```python
if request.app.state.state_store.get_settings()["auto_sync_domains"]:
    try:
        refresh_domains(request, require_auto=True)
    except Exception:
        pass
```

Import `_domain` from `src.api_auth`. Failure deliberately falls back to the cache and is already recorded by `refresh_domains()`.

- [ ] **Step 5: Verify GREEN and commit**

Run:

```bash
rtk .venv/bin/pytest tests/test_public_api.py tests/test_admin_api.py -q
```

Expected: all selected backend tests pass, including existing manual-sync concurrency and frozen-whitelist cases.

```bash
rtk git add src/admin_api.py src/api_server.py tests/test_admin_api.py tests/test_public_api.py
rtk git commit -m "fix: refresh public domains from Stalwart"
```

---

### Task 2: Style-preserving message sandbox

**Files:**
- Modify: `src/api_server.py:74-91,623-625,643-675`
- Modify: `frontend/src/components/SandboxFrame.vue`
- Test: `tests/test_public_api.py`
- Test: `frontend/src/tests/SandboxFrame.test.ts`
- Test: `frontend/src/tests/MessageReader.test.ts`

**Interfaces:**
- Produces: `GET /message-sandbox`, a fresh nonce-bearing renderer document and response CSP.
- `SandboxFrame` sends `{type, html, css, mode}` to `/message-sandbox` for message mode and `/sandbox` for content mode.

- [ ] **Step 1: Add failing renderer security tests**

Append to `tests/test_public_api.py`:

```python
def test_message_sandbox_allows_email_styles_but_only_its_nonce_script(client):
    first = client.get("/message-sandbox")
    second = client.get("/message-sandbox")
    csp = first.headers["content-security-policy"]
    nonce = re.search(r"script-src 'nonce-([^']+)'", csp).group(1)

    assert first.status_code == 200
    assert first.headers["x-frame-options"] == "SAMEORIGIN"
    assert f'nonce="{nonce}"' in first.text
    assert first.text != second.text
    assert "style-src 'unsafe-inline'" in csp
    assert "img-src data: https: http:" in csp
    assert "form-action 'none'" in csp
    assert "object-src 'none'" in csp
    assert "script-src 'unsafe-inline'" not in csp
    assert "allow-same-origin" not in first.text
```

Replace the first case in `frontend/src/tests/SandboxFrame.test.ts` with:

```typescript
it('posts message HTML to the nonce-protected opaque renderer', async () => {
  const postMessage = vi.fn()
  const contentWindow = vi.spyOn(HTMLIFrameElement.prototype, 'contentWindow', 'get')
    .mockReturnValue({ postMessage } as unknown as Window)
  const wrapper = mount(SandboxFrame, {
    props: { html: '<p style="color:red">Hello</p>', mode: 'message' },
  })
  const frame = wrapper.get('iframe')
  await frame.trigger('load')

  expect(frame.attributes('sandbox')).toBe(
    'allow-scripts allow-popups allow-popups-to-escape-sandbox',
  )
  expect(frame.attributes('sandbox')).not.toContain('allow-same-origin')
  expect(frame.attributes('src')).toBe('/message-sandbox?revision=0')
  expect(frame.attributes('srcdoc')).toBeUndefined()
  expect(postMessage).toHaveBeenCalledWith({
    type: 'tmail:sandbox-content',
    html: '<p style="color:red">Hello</p>',
    css: '',
    mode: 'message',
  }, '*')
  contentWindow.mockRestore()
})
```

In the existing `MessageReader.test.ts` case named `loads on selection, marks unread mail seen, and isolates HTML`, replace its three iframe assertions with:

```typescript
expect(wrapper.get('iframe').attributes('sandbox')).toContain('allow-scripts')
expect(wrapper.get('iframe').attributes('sandbox')).not.toContain('allow-same-origin')
expect(wrapper.get('iframe').attributes('src')).toBe('/message-sandbox?revision=0')
expect(wrapper.get('iframe').attributes('srcdoc')).toBeUndefined()
```

- [ ] **Step 2: Run both tests and verify RED**

Run:

```bash
rtk .venv/bin/pytest tests/test_public_api.py -k message_sandbox -vv
rtk npm --prefix frontend test -- --run src/tests/SandboxFrame.test.ts
```

Expected: backend returns 404 and frontend still uses `srcdoc` without `allow-scripts`.

- [ ] **Step 3: Add the nonce-protected renderer route**

Add `import secrets` to `src/api_server.py`. Replace the static message handling with a document builder:

```python
def _message_sandbox(nonce: str) -> str:
    return f'''<!doctype html>
<html><head><meta charset="utf-8"><title>Message content</title></head><body>
<script nonce="{nonce}">
"use strict";
addEventListener("message", (event) => {{
  const value = event.data;
  if (event.source !== parent || !value || value.type !== "tmail:sandbox-content") return;
  if (value.mode !== "message" || typeof value.html !== "string") return;
  document.open();
  document.write('<!doctype html><html><head><meta charset="utf-8">');
  document.write('<meta name="viewport" content="width=device-width,initial-scale=1">');
  document.write('<style>html,body{{margin:0;padding:0;max-width:100%;overflow-wrap:anywhere}}body{{padding:16px}}img{{max-width:100%;height:auto}}table{{max-width:100%}}</style>');
  document.write('</head><body>');
  document.write(value.html);
  document.write('</body></html>');
  document.close();
  for (const link of document.links) {{
    link.target = "_blank";
    link.rel = "noopener noreferrer";
  }}
}}, {{once: true}});
</script></body></html>'''
```

Register the route next to `/sandbox`:

```python
@app.get("/message-sandbox", include_in_schema=False, response_class=HTMLResponse)
def message_sandbox_document():
    nonce = secrets.token_urlsafe(24)
    response = HTMLResponse(_message_sandbox(nonce))
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; "
        f"script-src 'nonce-{nonce}'; "
        "style-src 'unsafe-inline'; img-src data: https: http:; "
        "font-src data: https: http:; connect-src 'none'; frame-src 'none'; "
        "object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
    )
    return response
```

In `_set_security_headers()`, set `X-Frame-Options` to `SAMEORIGIN` when the path is either sandbox route. Add this branch before the `/docs` branch so middleware preserves the route's dynamic CSP:

```python
elif request.url.path == "/message-sandbox":
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'none'; frame-ancestors 'self'",
    )
```

- [ ] **Step 4: Send message content through the renderer**

In `SandboxFrame.vue`, remove `messageSource`, make both modes use a source URL, and post on load:

```typescript
const sandbox = computed(() => 'allow-scripts allow-popups allow-popups-to-escape-sandbox')
const sourceUrl = computed(() => `${props.mode === 'message' ? '/message-sandbox' : '/sandbox'}?revision=${revision.value}`)

function sendContent(): void {
  frame.value?.contentWindow?.postMessage({
    type: 'tmail:sandbox-content',
    html: props.html,
    css: props.css,
    mode: props.mode,
  }, '*')
}
```

The iframe becomes:

```vue
<iframe
  :key="revision"
  ref="frame"
  class="sandbox-frame"
  :sandbox="sandbox"
  :src="sourceUrl"
  :title="title || (mode === 'message' ? 'Message content' : 'Site content')"
  @load="sendContent"
/>
```

- [ ] **Step 5: Verify GREEN and commit**

Run:

```bash
rtk .venv/bin/pytest tests/test_public_api.py -k sandbox -q
rtk npm --prefix frontend test -- --run src/tests/SandboxFrame.test.ts src/tests/MessageReader.test.ts
```

Expected: renderer security and message-reader tests pass; no received HTML appears in Vue's DOM.

```bash
rtk git add src/api_server.py tests/test_public_api.py frontend/src/components/SandboxFrame.vue frontend/src/tests/SandboxFrame.test.ts frontend/src/tests/MessageReader.test.ts
rtk git commit -m "fix: preserve safe email HTML styling"
```

---

### Task 3: Reference-matched public mail layout

**Files:**
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/components/AddressPanel.vue`
- Modify: `frontend/src/components/InboxView.vue`
- Modify: `frontend/src/components/MessageReader.vue`
- Modify: `frontend/src/styles.css`
- Test: `frontend/src/tests/address-flow.test.ts`
- Test: `frontend/src/tests/InboxView.test.ts`

**Interfaces:**
- `AddressPanel` accepts optional `appName` and `logoDataUrl` props.
- `InboxView` accepts optional `appName` and `logoDataUrl` props in addition to `session` and `fetchSeconds`.
- Both public screens expose direct children `.account-rail`, `.message-list`/`.saved-inboxes`, and `.mail-detail` inside `.three-pane`.

- [ ] **Step 1: Add failing structure tests**

In the existing address-flow test after mounting the home route, assert:

```typescript
expect(wrapper.get('.address-layout').classes()).toContain('three-pane')
expect(wrapper.get('.account-rail').text()).toContain('Temporary Inbox')
expect(wrapper.get('.saved-inboxes').exists()).toBe(true)
expect(wrapper.get('.address-detail').text()).toContain('Create an address')
```

In `InboxView.test.ts`, append:

```typescript
it('uses the approved account, message-list, and reader columns without fake navigation', async () => {
  const wrapper = mount(InboxView, {
    props: { session, fetchSeconds: 20, appName: 'Temporary Inbox', logoDataUrl: '' },
  })
  await flushPromises()

  expect(wrapper.classes()).toContain('three-pane')
  expect(wrapper.get('.account-rail').text()).toContain(session.address)
  expect(wrapper.get('.message-list').exists()).toBe(true)
  expect(wrapper.get('.mail-detail').exists()).toBe(true)
  expect(wrapper.text()).not.toMatch(/Sent|Contacts|Addresses/)
})
```

In `MessageReader.test.ts`, append:

```typescript
it('returns from the mobile reader to the message list', async () => {
  const wrapper = mount(MessageReader, { props: { token: 'signed', id: 'one' } })
  await flushPromises()

  await wrapper.get('[data-action="close"]').trigger('click')

  expect(wrapper.emitted('close')).toHaveLength(1)
})
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
rtk npm --prefix frontend test -- --run src/tests/address-flow.test.ts src/tests/InboxView.test.ts
```

Expected: selectors `.three-pane`, `.account-rail`, `.saved-inboxes`, and `.mail-detail` are absent.

- [ ] **Step 3: Move public controls into three panes**

Add these optional branding props to `AddressPanel.vue`:

```typescript
withDefaults(defineProps<{
  initialError?: string
  appName?: string
  logoDataUrl?: string
}>(), { initialError: '', appName: 'Temporary Inbox', logoDataUrl: '' })
```

Add these props to `InboxView.vue`:

```typescript
const props = withDefaults(defineProps<{
  session: AddressSession
  fetchSeconds: number
  appName?: string
  logoDataUrl?: string
}>(), { appName: 'Temporary Inbox', logoDataUrl: '' })
```

In `InboxView.vue`, replace the current `<header class="inbox-toolbar">` with this first direct child of the root section:

```vue
<aside class="account-rail">
  <a class="rail-brand" href="/">
    <img v-if="logoDataUrl" :src="logoDataUrl" alt="">
    <span>{{ appName }}</span>
  </a>
  <div class="address-card">
    <small>Your current address</small>
    <strong id="inbox-title">{{ session.address }}</strong>
    <button class="secondary-button" type="button" @click="copyAddress">Copy</button>
  </div>
  <div class="rail-actions">
    <button class="secondary-button" type="button" :disabled="refreshing" @click="refresh">Refresh</button>
    <button class="primary-button" type="button" @click="emit('newAddress')">New address</button>
  </div>
  <nav class="rail-nav" aria-label="Mailbox navigation">
    <span aria-current="page">Inbox <b>{{ collection?.['hydra:totalItems'] ?? 0 }}</b></span>
    <a href="/docs">API docs</a>
    <a href="/admin">Admin</a>
  </nav>
  <div class="api-status"><i aria-hidden="true" /> API status <strong>Healthy</strong></div>
  <button class="rail-signout" type="button" @click="emit('newAddress')">Leave inbox</button>
  <p v-if="notice" class="toolbar-notice" aria-live="polite">{{ notice }}</p>
</aside>
```

Add `three-pane` to the root section. Remove `.inbox-grid`; move its existing `.message-list` child directly after `.account-rail`, and wrap its existing `MessageReader`/`.reader-placeholder` branch unchanged in `<div class="mail-detail">` as the third direct child.

Apply the same three direct panes in `AddressPanel.vue`: `.account-rail` contains the brand, API/docs/admin links, and healthy state; `.saved-inboxes` contains remembered inbox buttons or an empty explanation; `.address-detail` contains the existing address form. Do not add Sent, Contacts, or fake mailbox actions.

In `App.vue`, pass `site?.appName` and `site?.logoDataUrl` to both components. Remove the default `.site-header` and `.site-footer`; keep configured header/footer/ad sandbox frames and the cookie notice so saved customization still works.

- [ ] **Step 4: Replace the editorial visual tokens and layout**

Replace the top-level, address, inbox, reader, button, and responsive rules in `styles.css` with these exact foundations, then map the existing state/form selectors to the same tokens:

```css
:root {
  color-scheme: light;
  font-family: Arial, Helvetica, sans-serif;
  --canvas: #f8f9fb;
  --surface: #ffffff;
  --surface-selected: #eef3ff;
  --ink: #111827;
  --muted: #6b7280;
  --line: #e5e7eb;
  --primary: #2448c8;
  --accent: #17379e;
  --green: #169b55;
  --red: #d9363e;
  --radius: 5px;
  background: var(--canvas);
  color: var(--ink);
}

body { margin: 0; min-width: 320px; min-height: 100dvh; background: var(--canvas); }
.app-frame { width: 100%; min-height: 100dvh; background: var(--surface); }
.three-pane {
  display: grid;
  grid-template-columns: minmax(13.5rem, 0.72fr) minmax(18rem, 0.9fr) minmax(28rem, 1.9fr);
  min-height: 100dvh;
  background: var(--surface);
}
.account-rail,
.message-list,
.saved-inboxes { min-width: 0; border-right: 1px solid var(--line); }
.account-rail { display: flex; flex-direction: column; gap: 1rem; padding: 1.25rem 1rem; }
.rail-brand { display: flex; align-items: center; gap: .65rem; min-height: 2.25rem; font-weight: 700; text-decoration: none; }
.rail-brand img { width: 1.75rem; height: 1.75rem; object-fit: contain; }
.address-card,
.api-status { padding: .9rem; border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); }
.address-card { display: grid; gap: .65rem; }
.address-card strong { overflow-wrap: anywhere; font-size: .86rem; }
.address-card small,
.toolbar-notice { color: var(--muted); font-size: .72rem; }
.rail-actions { display: grid; grid-template-columns: 1fr 1.25fr; gap: .5rem; }
.rail-nav { display: grid; gap: .3rem; }
.rail-nav a,
.rail-nav span { display: flex; justify-content: space-between; padding: .68rem .75rem; border-radius: var(--radius); font-size: .8rem; text-decoration: none; }
.rail-nav [aria-current="page"] { color: var(--primary); background: var(--surface-selected); font-weight: 700; }
.api-status { margin-top: auto; color: var(--muted); font-size: .72rem; }
.api-status i { display: inline-block; width: .45rem; height: .45rem; margin-right: .35rem; border-radius: 50%; background: var(--green); }
.api-status strong { display: block; margin: .3rem 0 0 .85rem; color: var(--green); }
.rail-signout { border: 0; padding: .7rem; background: transparent; color: var(--muted); text-align: left; }
button { min-height: 2.35rem; border-radius: var(--radius); transition: background-color .18s ease, transform .18s ease; }
button:active { transform: translateY(1px); }
.primary-button { border: 1px solid var(--primary); background: var(--primary); color: #fff; }
.secondary-button { border: 1px solid var(--line); background: var(--surface); color: var(--ink); }
.message-list { background: var(--surface); }
.list-heading { min-height: 4.7rem; padding: 1.25rem 1rem; border-bottom: 1px solid var(--line); }
.message-row { padding: 1rem; border: 0; border-bottom: 1px solid var(--line); border-radius: 0; background: var(--surface); }
.message-row:hover,
.message-row.selected { background: var(--surface-selected); }
.message-row.unread { border-left: 3px solid var(--primary); }
.mail-detail { min-width: 0; overflow: auto; background: var(--surface); }
.message-reader { padding: 1.5rem 1.75rem; }
.reader-header { border-bottom: 1px solid var(--line); }
.reader-header h2 { font-size: 1.3rem; letter-spacing: -.025em; }
.sandbox-frame { width: 100%; min-height: 31rem; border: 1px solid var(--line); background: #fff; }
.saved-inboxes { padding: 1.25rem 1rem; }
.address-detail { display: grid; align-content: center; padding: clamp(2rem, 7vw, 6rem); }

@media (max-width: 900px) {
  .three-pane { grid-template-columns: 12rem minmax(17rem, 1fr); }
  .mail-detail,
  .address-detail { grid-column: 2; }
  .inbox-view .mail-detail:has(.message-reader) { position: fixed; inset: 0; z-index: 2; }
}

@media (max-width: 640px) {
  .three-pane { display: block; min-height: 100dvh; }
  .account-rail { border-right: 0; border-bottom: 1px solid var(--line); }
  .message-list,
  .saved-inboxes { border-right: 0; }
  .address-detail,
  .message-reader { padding: 1rem; }
  .reader-header { display: grid; gap: 1rem; }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; transition: none !important; }
}
```

Add a visible mobile **Back to inbox** button in `MessageReader.vue` that emits a new `close` event; `InboxView` handles it by setting `selectedId = null`. Hide it above 900px with CSS rather than user-agent detection.

- [ ] **Step 5: Verify GREEN and commit**

Run:

```bash
rtk npm --prefix frontend test -- --run src/tests/address-flow.test.ts src/tests/InboxView.test.ts src/tests/MessageReader.test.ts
rtk npm --prefix frontend run build
```

Expected: public structure, behavior, type checking, and production build pass.

```bash
rtk git add frontend/src/App.vue frontend/src/components/AddressPanel.vue frontend/src/components/InboxView.vue frontend/src/components/MessageReader.vue frontend/src/styles.css frontend/src/tests/address-flow.test.ts frontend/src/tests/InboxView.test.ts frontend/src/tests/MessageReader.test.ts
rtk git commit -m "feat: match public mail client layout"
```

---

### Task 4: Reference-matched administration layout

**Files:**
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/admin/AdminApp.vue`
- Modify: `frontend/src/styles.css`
- Test: `frontend/src/tests/AdminApp.test.ts`

**Interfaces:**
- `AdminApp` accepts `appName?: string` and `logoDataUrl?: string` for the pre-login rail.
- Authenticated admin renders `.admin-shell.three-pane` with `.admin-account-rail`, `.admin-sidebar`, and `.admin-content` as direct children.

- [ ] **Step 1: Add the failing admin layout test**

After login in `AdminApp.test.ts`, add:

```typescript
expect(wrapper.get('.admin-shell').classes()).toContain('three-pane')
expect(wrapper.get('.admin-account-rail').text()).toContain('tmail')
expect(wrapper.get('.admin-sidebar').text()).toContain('Dashboard')
expect(wrapper.get('.admin-content [role="tabpanel"]').exists()).toBe(true)
expect(wrapper.text()).not.toMatch(/Sent|Contacts|Addresses/)
```

Update the login-state copy assertion to require `Your session is kept for 12 hours on this device.` and reject the obsolete `Sign in again after a reload.` text.

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
rtk npm --prefix frontend test -- --run src/tests/AdminApp.test.ts
```

Expected: `.admin-account-rail` and `.three-pane` are absent, and old login copy remains.

- [ ] **Step 3: Add the admin account rail and keep tab semantics**

Add these optional branding props. Keep the existing login/session/CSRF methods and tab keyboard handling unchanged.

```typescript
withDefaults(defineProps<{ appName?: string; logoDataUrl?: string }>(), {
  appName: 'Temporary Inbox',
  logoDataUrl: '',
})
```

Add `three-pane` to `.admin-shell`, then insert this as its first direct child:

```vue
<aside class="admin-account-rail account-rail">
  <a class="rail-brand" href="/">
    <img v-if="settings.site.logoDataUrl || logoDataUrl" :src="settings.site.logoDataUrl || logoDataUrl" alt="">
    <span>{{ settings.site.appName || appName }}</span>
  </a>
  <nav class="rail-nav" aria-label="Application navigation">
    <a href="/">Public inbox</a>
    <span aria-current="page">Administration</span>
    <a href="/docs">API docs</a>
  </nav>
  <div class="api-status"><i aria-hidden="true" /> API status <strong>Healthy</strong></div>
  <button class="rail-signout" type="button" :disabled="pending || childBusy" @click="logout">
    {{ pending ? 'Logging out' : 'Log out' }}
  </button>
  <p v-if="error" class="form-error" role="alert">{{ error }}</p>
</aside>
```

Keep `.admin-sidebar` as the second direct child, replace its introductory `<div>` with `<div class="list-heading"><div><h2>Settings</h2><span>System configuration</span></div></div>`, and remove its old logout/error nodes. Keep `.admin-content` as the third direct child and change its tag from `<div>` to `<section>`.

Change login copy to `Your session is kept for 12 hours on this device. Credentials are never stored.` Pass `site?.appName` and `site?.logoDataUrl` from `App.vue`.

- [ ] **Step 4: Apply the shared visual system to admin panes**

Add these rules to `styles.css`, deleting conflicting old sidebar/card-shadow rules:

```css
.admin-account-rail { border-right: 1px solid var(--line); }
.admin-sidebar { min-width: 0; border-right: 1px solid var(--line); background: var(--surface); }
.admin-sidebar nav { display: grid; }
.admin-sidebar [role="tab"] {
  width: 100%;
  min-height: 3rem;
  border: 0;
  border-bottom: 1px solid var(--line);
  border-radius: 0;
  padding: .8rem 1rem;
  background: var(--surface);
  color: var(--ink);
  text-align: left;
}
.admin-sidebar [role="tab"][aria-selected="true"] {
  border-left: 3px solid var(--primary);
  padding-left: calc(1rem - 3px);
  background: var(--surface-selected);
  color: var(--primary);
  font-weight: 700;
}
.admin-content { min-width: 0; overflow: auto; padding: 1.5rem 1.75rem 3rem; background: var(--surface); }
.admin-content [role="tabpanel"] { max-width: 64rem; }
.admin-login { min-height: 100dvh; background: var(--canvas); }
.admin-login-panel { width: min(100% - 2rem, 28rem); border: 1px solid var(--line); box-shadow: none; background: var(--surface); }

@media (max-width: 900px) {
  .admin-shell.three-pane { grid-template-columns: 12rem minmax(18rem, 1fr); }
  .admin-content { grid-column: 2; }
}

@media (max-width: 640px) {
  .admin-sidebar { border-right: 0; }
  .admin-sidebar nav { display: flex; overflow-x: auto; }
  .admin-sidebar [role="tab"] { width: auto; white-space: nowrap; }
  .admin-content { padding: 1rem; }
}
```

- [ ] **Step 5: Verify GREEN and commit**

Run:

```bash
rtk npm --prefix frontend test -- --run src/tests/AdminApp.test.ts
rtk npm --prefix frontend run build
```

Expected: all 20+ admin behavior tests pass, tab keyboard behavior remains intact, and the build succeeds.

```bash
rtk git add frontend/src/App.vue frontend/src/admin/AdminApp.vue frontend/src/styles.css frontend/src/tests/AdminApp.test.ts
rtk git commit -m "feat: match administration mail client layout"
```

---

### Task 5: Integrated verification against remote Stalwart

**Files:**
- Modify only files required by failures found in this task.

**Interfaces:**
- Consumes the complete implementation from Tasks 1–4.
- Produces a tested build and live evidence for domains, inbox reads, and message renderer policy.

- [ ] **Step 1: Run complete automated verification**

Run independently:

```bash
rtk .venv/bin/pytest -q
rtk npm --prefix frontend test -- --run
rtk npm --prefix frontend run build
rtk git diff --check
```

Expected: every Python and Vitest test passes, Vue type checking and Vite build succeed, and `git diff --check` prints nothing.

- [ ] **Step 2: Restart the local API and retain the Vite server**

Restart with the existing local configuration:

```bash
rtk env TMAIL_CONFIG=/home/arcrek/workspace/tmail_add_domain/config.json .venv/bin/python -m src.api_server
```

Expected: Uvicorn reports startup on `http://127.0.0.1:8000`; Vite remains at `http://127.0.0.1:5173`.

- [ ] **Step 3: Verify live domains and mail without printing secrets or content**

Set the task-scoped `TMAIL_TEST_ADDRESS` environment variable to an existing test inbox, then use an `httpx.Client` through port 5173 to assert:

```python
import os

known_address = os.environ["TMAIL_TEST_ADDRESS"]
domains = client.get("/domains")
assert domains.status_code == 200
assert domains.json()["hydra:totalItems"] > 0

token = client.post("/token", json={"address": known_address}).json()["token"]
headers = {"Authorization": f"Bearer {token}"}
messages = client.get("/messages", headers=headers)
assert messages.status_code == 200
detail = client.get(f"/messages/{messages.json()['hydra:member'][0]['id']}", headers=headers)
assert detail.status_code == 200

renderer = client.get("/message-sandbox")
assert "style-src 'unsafe-inline'" in renderer.headers["content-security-policy"]
assert "script-src 'unsafe-inline'" not in renderer.headers["content-security-policy"]
```

Print only statuses, counts, and boolean assertions. Do not print the token, address, sender, subject, or message HTML.

- [ ] **Step 4: Visually compare the three panes and styled message**

Open the known inbox at `http://127.0.0.1:5173/<encoded-address>` and compare at desktop width with the supplied reference:

- left account rail, middle message list, and right reader are simultaneously visible;
- white surfaces, gray dividers, blue selected/actions, compact typography, and flat controls match;
- the SendTestMail message matches the styled reference panel/button rather than the unstyled serif rendering;
- `/admin` uses the same rail/list/detail hierarchy;
- at 640px, panes stack and the reader exposes **Back to inbox**.

- [ ] **Step 5: Commit only verified follow-up fixes**

If Step 1–4 required changes, rerun the affected focused test before staging those exact files, then commit:

```bash
rtk git commit -m "fix: close frontend correction gaps"
```

Expected: working tree contains only the pre-existing untracked `.codegraph/` directory.
