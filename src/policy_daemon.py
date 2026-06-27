from __future__ import annotations
import logging
import os
import socketserver
import sys

from src.config import load_config
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
_cache: DomainCache = None
_jmap: JmapClient = None


class PolicyHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
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
            if mx_matches(domain, _config.mx_hostname):
                ok = _jmap.provision_domain(domain)
                if ok:
                    _cache.add(domain)
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
    global _config, _cache, _jmap
    config_path = os.environ.get("TMAIL_CONFIG", "/opt/tmail-policy/config.json")
    _config = load_config(config_path)

    _cache = DomainCache(_config.cache_file)
    _cache.load()

    _jmap = JmapClient(_config.jmap_url, _config.jmap_token, _config.catchall_address)

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
