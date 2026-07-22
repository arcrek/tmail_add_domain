# Task 2 Report: Style-preserving message sandbox

## Result

Received-email HTML now renders through a dedicated `/message-sandbox` document. The iframe remains opaque because it has `allow-scripts` but not `allow-same-origin`; the renderer accepts one parent message, writes the received HTML into its isolated document, and preserves inline email styling under a nonce-protected CSP. The existing `/sandbox` content-mode renderer is unchanged.

Base commit: `d42a10483752bf378ee4be195aadf9bd7cfd1f52`

## Files changed

- `src/api_server.py`
  - Added fresh cryptographic nonce generation with `secrets.token_urlsafe(24)`.
  - Added `_message_sandbox()` and `GET /message-sandbox`.
  - Preserved the route's dynamic CSP in security middleware and allowed same-origin framing at the response-header layer.
- `frontend/src/components/SandboxFrame.vue`
  - Routed message mode to `/message-sandbox` and content mode to the existing `/sandbox`.
  - Removed received HTML from `srcdoc`; both modes now send the existing structured `postMessage` payload on iframe load.
  - Limited message-mode delivery to once per iframe revision so a hostile self-navigation cannot receive the email body on a later load.
  - Kept the iframe opaque by omitting `allow-same-origin`.
- `tests/test_public_api.py`
  - Added nonce freshness, CSP, and framing regression coverage for `/message-sandbox`.
- `frontend/src/tests/SandboxFrame.test.ts`
  - Added message-mode renderer URL, sandbox flags, absence of `srcdoc`, and payload coverage.
- `frontend/src/tests/MessageReader.test.ts`
  - Updated the received-message integration assertions for the opaque renderer path.

## TDD evidence

### RED

After changing tests and before production code:

- `rtk .venv/bin/pytest tests/test_public_api.py -k message_sandbox -vv`
  - Result: `1 failed, 42 deselected`.
  - Expected failure: `/message-sandbox` had no nonce-bearing `script-src`; nonce extraction returned `None`.
- `rtk npm --prefix frontend test -- --run src/tests/SandboxFrame.test.ts`
  - Result: `1 failed, 2 passed`.
  - Expected failure: message mode still used `srcdoc` and omitted `allow-scripts` instead of loading `/message-sandbox`.
- Reviewer-discovered navigation regression: a second synthetic iframe `load` initially called `postMessage` twice.
  - Result before the message-only delivery gate: `1 failed, 2 passed`; expected one call, received two.
  - Result after the gate: the focused frontend suite returned `13 passed`.

### GREEN

After the minimum production changes:

- `rtk .venv/bin/pytest tests/test_public_api.py -k sandbox -q`
  - Result: `3 passed, 40 deselected`.
- `rtk npm --prefix frontend test -- --run src/tests/SandboxFrame.test.ts src/tests/MessageReader.test.ts`
  - Result: `2 test files passed; 13 tests passed`.

## Broader verification

- `rtk .venv/bin/pytest tests/test_public_api.py -q`
  - Result: `43 passed in 2.31s`.
- `rtk npm --prefix frontend test -- --run`
  - Result: `8 test files passed; 61 tests passed`.
- `rtk npm --prefix frontend run build`
  - Result: `vue-tsc --noEmit` and Vite production build completed successfully.
- `rtk git diff --check`
  - Result: clean; no whitespace errors.

The FastAPI TestClient checks hung when run inside the restricted sandbox. As permitted by the task brief, backend tests were rerun outside it and completed normally.

## Security self-review

- Nonce generation uses Python's `secrets` module and creates a new 24-byte URL-safe value for every route response; tests confirm successive renderer documents differ.
- The response CSP permits only the matching nonce bootstrap script. It does not enable `'unsafe-inline'` for scripts, so received `<script>` elements and inline event handlers cannot execute.
- Inline styles are allowed solely inside the opaque renderer to preserve email presentation. Images and fonts may load from `data:`, HTTPS, or HTTP as required; `connect-src`, `frame-src`, `object-src`, `base-uri`, and `form-action` are denied.
- Middleware uses `setdefault` for `/message-sandbox`, preserving the route's nonce-specific CSP rather than replacing it with a static policy.
- The iframe enables scripts only so the trusted nonce bootstrap can run. It omits `allow-same-origin`, leaving the child with an opaque origin and preventing received HTML from accessing the parent DOM or application origin.
- The bootstrap accepts exactly one message, requires `event.source === parent`, the existing payload type, `mode === "message"`, and a string HTML body.
- The parent sends received HTML only once per iframe revision. If hostile markup self-navigates the frame (for example via meta refresh), a later `load` cannot repost the email body to the new document. This gate is message-only, so existing admin/content-mode delivery behavior is unchanged.
- Links are rewritten after document replacement to open in a new browsing context with `noopener noreferrer`. The sandbox allows popups and escape only for those user-activated destinations; it does not allow top navigation.
- Received HTML no longer appears in Vue's DOM or an iframe `srcdoc` attribute.
- The existing admin/content `/sandbox` document, its CSP, and content-mode payload contract were not expanded.

## Concerns

No implementation concerns found. Remote images/fonts remain capable of sender tracking because preserving received-email resources explicitly requires HTTP(S) image/font loading; that is existing product policy in this task's CSP, not a new unrestricted script or network capability.
