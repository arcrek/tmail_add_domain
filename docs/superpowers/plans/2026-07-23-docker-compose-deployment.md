# Docker Compose Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the Vue frontend and FastAPI service as separate Docker Compose services behind one public frontend port.

**Architecture:** A multi-stage frontend image builds with Node and serves the SPA through Nginx. Nginx proxies same-origin API, admin, documentation, and sandbox routes to an internal-only Python API container. A named volume owns the API's writable runtime configuration, domain cache, and SQLite state; the repository `config.json` is only a first-start seed.

**Tech Stack:** Docker Compose, Python 3.12 slim, FastAPI/Uvicorn, Node 22 Alpine, Vite, Nginx Alpine, pytest.

## Global Constraints

- Publish only `${TMAIL_HTTP_BIND:-127.0.0.1}:${TMAIL_HTTP_PORT:-8080}:80`; never publish the API container port.
- Keep Stalwart, Postfix, the policy daemon, the janitor, and TLS outside this Compose project.
- Preserve all same-origin routes used by the Vue application.
- Mount `config.json` read-only as a seed; never bake it into an image.
- Persist `/var/lib/tmail-policy` in the `tmail-data` named volume.
- Run the API as non-root.
- Add no Python, Node, or browser dependency.
- Preserve the existing systemd deployment path.

---

## File Structure

- `src/api_server.py`: allow Docker-specific API bind overrides while keeping configured defaults.
- `tests/test_api_static.py`: regression coverage for configured and environment-overridden bind values.
- `Dockerfile.api`: minimal non-root FastAPI image.
- `Dockerfile.frontend`: multi-stage Vite build and Nginx runtime.
- `docker/api-entrypoint.sh`: securely seed the writable runtime config once, then execute the API command.
- `docker/nginx.conf`: serve the SPA and proxy the exact backend route families.
- `compose.yaml`: connect the two services, persistence, health checks, and one published port.
- `.dockerignore`: exclude credentials, local environments, caches, and build output.
- `tests/test_docker_deployment.py`: dependency-free deployment contract and config-seeding tests.
- `README.md`: operator commands, persistence semantics, reverse-proxy requirement, and reset warning.

---

### Task 1: Container Bind Overrides

**Files:**
- Modify: `tests/test_api_static.py:92-106`
- Modify: `src/api_server.py:740-744`

**Interfaces:**
- Consumes: existing `TMAIL_CONFIG`, `Config.api_listen_addr`, and `Config.api_listen_port`.
- Produces: optional `TMAIL_API_HOST` and `TMAIL_API_PORT` environment overrides used only by the API process.

- [ ] **Step 1: Write the failing environment-override test**

Add this test after `test_main_uses_environment_config_and_api_bind`:

```python
def test_main_allows_container_bind_overrides(config_path, monkeypatch):
    called = {}
    monkeypatch.setenv("TMAIL_CONFIG", str(config_path))
    monkeypatch.setenv("TMAIL_API_HOST", "0.0.0.0")
    monkeypatch.setenv("TMAIL_API_PORT", "8000")
    monkeypatch.setattr(api_server.uvicorn, "run", lambda app, host, port: called.update(
        app=app, host=host, port=port
    ))

    api_server.main()

    assert called["host"] == "0.0.0.0"
    assert called["port"] == 8000
```

- [ ] **Step 2: Run the focused test and verify the red state**

Run:

```bash
.venv/bin/python -m pytest tests/test_api_static.py::test_main_allows_container_bind_overrides -q
```

Expected: FAIL because `main()` still passes `127.0.0.2:8765`.

- [ ] **Step 3: Implement the minimum bind override**

Replace the `uvicorn.run` call in `main()` with:

```python
    host = os.environ.get("TMAIL_API_HOST", cfg.api_listen_addr)
    port = int(os.environ.get("TMAIL_API_PORT", cfg.api_listen_port))
    uvicorn.run(app, host=host, port=port)
```

The existing test continues to prove configured values remain the default.

- [ ] **Step 4: Run focused and full backend tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_api_static.py -q
.venv/bin/python -m pytest -q
```

Expected: the focused file and all backend tests pass.

- [ ] **Step 5: Commit the bind override**

```bash
git add src/api_server.py tests/test_api_static.py
git commit -m "feat: allow container API bind override"
```

---

### Task 2: Compose Services, Persistence, Proxy, and Operator Docs

**Files:**
- Create: `tests/test_docker_deployment.py`
- Create: `Dockerfile.api`
- Create: `Dockerfile.frontend`
- Create: `docker/api-entrypoint.sh`
- Create: `docker/nginx.conf`
- Create: `compose.yaml`
- Create: `.dockerignore`
- Modify: `README.md:72-97`

**Interfaces:**
- Consumes: `TMAIL_API_HOST`, `TMAIL_API_PORT`, existing `config.json`, `requirements.txt`, `frontend/package-lock.json`, and Vite output in `frontend/dist`.
- Produces: frontend at `${TMAIL_HTTP_BIND:-127.0.0.1}:${TMAIL_HTTP_PORT:-8080}`, internal API at `api:8000`, runtime config at `/var/lib/tmail-policy/config.json`, and named volume `tmail-data`.

- [ ] **Step 1: Write failing deployment contract tests**

Create `tests/test_docker_deployment.py`:

```python
from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_api_entrypoint_seeds_runtime_config_once(tmp_path):
    seed = tmp_path / "seed.json"
    runtime = tmp_path / "runtime.json"
    marker = tmp_path / "ran"
    seed.write_text('{"version": 1}\n')
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "TMAIL_CONFIG": str(runtime),
        "TMAIL_CONFIG_SEED": str(seed),
    }
    command = [
        "sh",
        str(ROOT / "docker/api-entrypoint.sh"),
        sys.executable,
        "-c",
        f"from pathlib import Path; Path({str(marker)!r}).write_text('ok')",
    ]

    subprocess.run(command, cwd=ROOT, env=env, check=True)
    assert runtime.read_text() == '{"version": 1}\n'
    assert stat.S_IMODE(runtime.stat().st_mode) == 0o600
    assert marker.read_text() == "ok"

    seed.write_text('{"version": 2}\n')
    subprocess.run(command, cwd=ROOT, env=env, check=True)
    assert runtime.read_text() == '{"version": 1}\n'


def test_compose_exposes_only_frontend_and_persists_runtime():
    compose = (ROOT / "compose.yaml").read_text()

    assert "${TMAIL_HTTP_BIND:-127.0.0.1}:${TMAIL_HTTP_PORT:-8080}:80" in compose
    assert "TMAIL_API_HOST: 0.0.0.0" in compose
    assert 'TMAIL_API_PORT: "8000"' in compose
    assert "FORWARDED_ALLOW_IPS: \"*\"" in compose
    assert "tmail-data:/var/lib/tmail-policy" in compose
    assert "./config.json:/run/tmail/config.json:ro" in compose
    assert "8000:8000" not in compose


def test_nginx_keeps_spa_and_backend_routes_same_origin():
    nginx = (ROOT / "docker/nginx.conf").read_text()

    assert "try_files $uri /index.html;" in nginx
    assert "proxy_pass http://api:8000;" in nginx
    for route in (
        "domains", "accounts", "token", "me", "messages", "sources", "site",
        "admin/api", "docs", "redoc", "openapi\\.json", "sandbox",
        "message-sandbox",
    ):
        assert route in nginx


def test_images_build_without_copying_runtime_secrets():
    api = (ROOT / "Dockerfile.api").read_text()
    frontend = (ROOT / "Dockerfile.frontend").read_text()
    ignored = (ROOT / ".dockerignore").read_text().splitlines()

    assert "gosu" in api
    assert "exec gosu tmail" in (ROOT / "docker/api-entrypoint.sh").read_text()
    assert "requirements-dev.txt" not in api
    assert "npm ci" in frontend
    assert "npm run build" in frontend
    assert "config.json" in ignored
```

- [ ] **Step 2: Run the deployment tests and verify the red state**

Run:

```bash
.venv/bin/python -m pytest tests/test_docker_deployment.py -q
```

Expected: FAIL because the deployment files do not exist.

- [ ] **Step 3: Create the secure one-time API entrypoint**

Create `docker/api-entrypoint.sh`:

```sh
#!/bin/sh
set -eu

runtime_config=${TMAIL_CONFIG:-/var/lib/tmail-policy/config.json}
seed_config=${TMAIL_CONFIG_SEED:-/run/tmail/config.json}
runtime_dir=$(dirname "$runtime_config")

mkdir -p "$runtime_dir"

if [ -L "$runtime_config" ]; then
    echo "ERROR: runtime config must not be a symlink: $runtime_config" >&2
    exit 1
fi

if [ ! -e "$runtime_config" ]; then
    if [ ! -f "$seed_config" ]; then
        echo "ERROR: config seed not found: $seed_config" >&2
        exit 1
    fi
    python3 -m src.config install-runtime "$runtime_config" < "$seed_config"
elif [ ! -f "$runtime_config" ]; then
    echo "ERROR: runtime config must be a regular file: $runtime_config" >&2
    exit 1
fi

if [ "$(id -u)" -eq 0 ]; then
    chown tmail:tmail "$runtime_dir" "$runtime_config"
    chmod 0700 "$runtime_dir"
    chmod 0600 "$runtime_config"
    exec gosu tmail "$@"
fi

exec "$@"
```

Make it executable:

```bash
chmod +x docker/api-entrypoint.sh
```

- [ ] **Step 4: Create the API image**

Create `Dockerfile.api`:

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY requirements.txt .
RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 tmail \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin tmail \
    && install -d -o tmail -g tmail -m 0700 /var/lib/tmail-policy

COPY src ./src
COPY docker/api-entrypoint.sh /usr/local/bin/tmail-api-entrypoint
RUN chmod 0755 /usr/local/bin/tmail-api-entrypoint

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/site', timeout=2).read()"]

ENTRYPOINT ["tmail-api-entrypoint"]
CMD ["python", "-m", "src.api_server"]
```

- [ ] **Step 5: Create the frontend image**

Create `Dockerfile.frontend`:

```dockerfile
FROM node:22-alpine AS build

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginx:1.27-alpine

COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
    CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1/"]
```

- [ ] **Step 6: Create the same-origin Nginx proxy**

Create `docker/nginx.conf`:

```nginx
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;
    client_max_body_size 5m;

    location ^~ /assets/ {
        try_files $uri =404;
        add_header Cache-Control "public, max-age=31536000, immutable";
    }

    location ~ ^/(?:domains(?:/|$)|accounts$|token$|me$|messages(?:/|$)|sources(?:/|$)|site$|admin/api(?:/|$)|docs(?:/|$)|redoc$|openapi\.json$|sandbox$|message-sandbox$) {
        proxy_pass http://api:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        try_files $uri /index.html;
        add_header Cache-Control "no-store";
    }
}
```

- [ ] **Step 7: Create Compose and build-context exclusions**

Create `compose.yaml`:

```yaml
services:
  api:
    build:
      context: .
      dockerfile: Dockerfile.api
    environment:
      TMAIL_CONFIG: /var/lib/tmail-policy/config.json
      TMAIL_CONFIG_SEED: /run/tmail/config.json
      TMAIL_API_HOST: 0.0.0.0
      TMAIL_API_PORT: "8000"
      FORWARDED_ALLOW_IPS: "*"
    volumes:
      - tmail-data:/var/lib/tmail-policy
      - ./config.json:/run/tmail/config.json:ro
    expose:
      - "8000"
    restart: unless-stopped

  frontend:
    build:
      context: .
      dockerfile: Dockerfile.frontend
    depends_on:
      api:
        condition: service_healthy
    ports:
      - "${TMAIL_HTTP_BIND:-127.0.0.1}:${TMAIL_HTTP_PORT:-8080}:80"
    restart: unless-stopped

volumes:
  tmail-data:
```

Create `.dockerignore`:

```text
.git
.codegraph
.worktrees
.venv
venv
__pycache__
*.py[cod]
.pytest_cache
*.egg-info
config.json
*.db
*.db-*
frontend/node_modules
frontend/dist
dist
build
```

- [ ] **Step 8: Run the deployment contract tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_docker_deployment.py -q
```

Expected: 4 tests pass.

- [ ] **Step 9: Validate Compose and build both images**

Run:

```bash
docker compose config --quiet
docker compose build
```

Expected: both commands exit successfully; `config.json` contents do not
appear in build output or image layers.

- [ ] **Step 10: Smoke-test the single public endpoint**

Run with a test-only Compose project and non-default port:

```bash
TMAIL_HTTP_PORT=18080 docker compose -p tmail-compose-verify up -d --wait
curl -fsS -o /dev/null http://127.0.0.1:18080/
curl -fsS -o /dev/null http://127.0.0.1:18080/site
curl -fsS -o /dev/null http://127.0.0.1:18080/docs
curl -fsS -o /dev/null http://127.0.0.1:18080/message-sandbox
TMAIL_HTTP_PORT=18080 docker compose -p tmail-compose-verify down -v
```

Expected: both services become healthy, all four requests return success, and
the isolated verification volume is removed. Do not print `config.json` or
container environment values.

- [ ] **Step 11: Document operator workflow**

Add this section before the existing `Production installation` section in
`README.md`:

````markdown
## Docker Compose

Create and secure `config.json` as described above. For container deployment,
keep `cache_file` and `state_db` under `/var/lib/tmail-policy`.

Build and start the frontend and API:

```bash
docker compose up -d --build
```

The frontend is available at `http://127.0.0.1:8080`. Change the published
port without editing Compose:

```bash
TMAIL_HTTP_PORT=8088 docker compose up -d
```

Inspect or stop the deployment:

```bash
docker compose ps
docker compose logs -f
docker compose down
```

The first start copies `config.json` into the `tmail-data` volume. Later
starts preserve that runtime copy so administrator changes survive rebuilds.
Changing the repository `config.json` does not overwrite an existing runtime
copy.

To intentionally erase runtime settings, cached domains, and mail-activity
metrics, stop the deployment and remove its volume:

```bash
docker compose down -v
```

Put an HTTPS reverse proxy in front of the published frontend port. The API is
not published separately; API docs remain available at `/docs` through the
frontend endpoint.
````

- [ ] **Step 12: Run all regression checks**

Run:

```bash
.venv/bin/python -m pytest -q
npm --prefix frontend test
npm --prefix frontend run build
git diff --check
```

Expected: all backend and frontend tests pass, the production frontend build
succeeds, and the diff check is clean.

- [ ] **Step 13: Commit the deployment**

```bash
git add .dockerignore Dockerfile.api Dockerfile.frontend compose.yaml docker/api-entrypoint.sh docker/nginx.conf tests/test_docker_deployment.py README.md
git commit -m "feat: add Docker Compose deployment"
```
