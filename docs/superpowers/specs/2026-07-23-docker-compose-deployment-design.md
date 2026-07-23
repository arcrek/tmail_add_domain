# Docker Compose Deployment Design

## Goal

Deploy the existing Vue frontend and FastAPI service as separate containers
behind one public HTTP endpoint. Preserve same-origin frontend behavior,
passwordless inbox routes, the administrator session, Mail.tm-compatible API
routes, API documentation, safe message rendering, and persistent runtime
settings.

## Scope

Compose deploys only:

- the production Vue/Vite frontend served by Nginx;
- the FastAPI web API.

Stalwart, Postfix, the policy daemon, and the email janitor remain external.
TLS remains the responsibility of the existing host reverse proxy.

## Architecture

The `frontend` service is the only published service. A multi-stage image uses
Node to run the existing Vite production build, then copies `frontend/dist`
into a minimal Nginx runtime image.

Nginx serves `/assets/*` directly and falls back to `index.html` for public
SPA routes, including `/`, `/admin`, and `/{mail-address}`. It proxies these
same-origin backend routes to the internal `api` service:

- `/domains`, `/accounts`, `/token`, `/me`, `/messages`, `/sources`, `/site`;
- `/admin/api/*`;
- `/docs`, `/redoc`, `/openapi.json`;
- `/sandbox`, `/message-sandbox`.

The `api` service uses a slim Python image, installs only
`requirements.txt`, copies `src/`, and runs as a non-root user. Compose sets
`TMAIL_API_HOST=0.0.0.0` and `TMAIL_API_PORT=8000` so an existing
configuration with `api_listen_addr` set to `127.0.0.1` remains usable.

Only the frontend port is published as `${TMAIL_HTTP_PORT:-8080}:80`. The API
port is available only on the Compose network. Nginx forwards the original
host and client forwarding headers.

## Configuration and Persistence

The required repository `config.json` is mounted read-only as an initial
seed. On the first start, the API entrypoint copies it to
`/var/lib/tmail-policy/config.json` inside the `tmail-data` named volume.
Later starts retain the volume copy.

This copy is necessary because administrator updates atomically replace the
runtime configuration file; Docker cannot replace a single bind-mounted
file. The named volume also persists the configured domain cache and SQLite
state paths under `/var/lib/tmail-policy`.

Changing the repository seed after first start does not overwrite runtime
settings. To replace the runtime configuration, the operator updates it
through the administrator UI or deliberately recreates the data volume.

Secrets remain in `config.json`; they are not baked into either image.

## Runtime Behavior

Both services use restart policies and health checks. The frontend waits for
the API health check before starting. A failed or placeholder web secret
causes the API to fail during its existing configuration validation.

The deployment is intended to sit behind an HTTPS reverse proxy. HTTPS is
required for the existing secure administrator session cookie.

## Files

- `Dockerfile.api`: FastAPI image.
- `Dockerfile.frontend`: Vite build and Nginx runtime image.
- `docker/api-entrypoint.sh`: one-time runtime-config seeding.
- `docker/nginx.conf`: SPA serving and same-origin API proxy rules.
- `compose.yaml`: service, network, volume, port, and health definitions.
- `.dockerignore`: excludes secrets, local environments, Git data, and build
  output from build contexts.
- `README.md`: concise Compose setup, lifecycle, persistence, and TLS notes.

## Verification

Verification covers:

- existing Python and frontend test suites;
- frontend production build;
- Dockerfile and Compose configuration validation;
- image builds;
- first-start config seeding and retained runtime data;
- API and frontend health checks;
- SPA fallback, direct address paths, API routes, documentation, and sandbox
  proxy routes through the single published frontend port.
