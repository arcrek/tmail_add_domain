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
    assert 'FORWARDED_ALLOW_IPS: "*"' in compose
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
