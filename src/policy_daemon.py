from __future__ import annotations
import logging
import os
import socketserver
import sys
import threading

from src.api_state import StateStore
from src.config import ConfigStore
from src.domain_cache import DomainCache
from src.jmap_client import JmapClient
from src.mx_checker import MxLookupError, mx_matches

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

_config = None
_config_store: ConfigStore = None
_cache: DomainCache = None
_state: StateStore = None
_jmap: JmapClient = None
_jmap_fingerprint = None
_jmap_lock = threading.Lock()


def _runtime():
    global _config, _jmap, _jmap_fingerprint
    with _jmap_lock:
        config = _config_store.get()
        fingerprint = (config.jmap_url, config.jmap_token, config.catchall_address)
        if _jmap is None or fingerprint != _jmap_fingerprint:
            _jmap = JmapClient(*fingerprint)
            _jmap_fingerprint = fingerprint
        _config = config
        return config, _jmap


class PolicyHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        config, jmap = _runtime()
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

        if not domain:
            self.wfile.write(b"action=REJECT Invalid recipient\n\n")
            return

        if _cache.contains(domain):
            self.wfile.write(b"action=OK\n\n")
            return

        try:
            if mx_matches(domain, config.mx_hostname):
                ok = jmap.provision_domain(domain)
                if ok:
                    _cache.add(domain)
                    try:
                        _state.record_event("domain_provisioned", domain)
                    except Exception as exc:
                        logger.warning("Metric write failed for %s: %s", domain, exc)
                    logger.info("Provisioned: %s", domain)
                    self.wfile.write(b"action=OK\n\n")
                else:
                    logger.error("JMAP provision failed: %s", domain)
                    self.wfile.write(b"action=DEFER_IF_PERMIT Service temporarily unavailable\n\n")
            else:
                logger.debug("MX mismatch, rejecting: %s", domain)
                self.wfile.write(b"action=REJECT\n\n")
        except MxLookupError as exc:
            logger.warning("DNS transient error for %s: %s", domain, exc)
            self.wfile.write(b"action=DEFER_IF_PERMIT DNS lookup failed, try again later\n\n")


def main() -> None:
    global _config, _config_store, _cache, _state, _jmap, _jmap_fingerprint
    config_path = os.environ.get("TMAIL_CONFIG", "/var/lib/tmail-policy/config.json")
    _config_store = ConfigStore(config_path)
    _config = _config_store.get()

    _cache = DomainCache(_config.cache_file)
    _cache.load()
    _state = StateStore(_config.state_db)

    _jmap = JmapClient(_config.jmap_url, _config.jmap_token, _config.catchall_address)
    _jmap_fingerprint = (_config.jmap_url, _config.jmap_token, _config.catchall_address)

    existing = _jmap.list_domains()
    if existing:
        _cache.add_many(existing)
        logger.info("Pre-loaded %d domains from Stalwart", len(existing))

    socketserver.ThreadingTCPServer.allow_reuse_address = True
    server = socketserver.ThreadingTCPServer(
        (_config.listen_addr, _config.listen_port),
        PolicyHandler,
    )
    logger.info("Listening on %s:%d", _config.listen_addr, _config.listen_port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
