"""The Host header values the SSE endpoint accepts (mcp-proxy ``--allowed-host``).

Since 0.13.3 mcp-proxy answers 421 to every request whose Host header is not a
loopback address or listed with ``--allowed-host``. Home Assistant reaches the
add-on by the host's IP address, the host name or the add-on's internal host
name, so these come from the Supervisor; the ``allowed_hosts`` option adds
anything else (a DNS name, a reverse proxy).

Prints one authority per line for the run script. Without the Supervisor only
the configured names are printed; an entry mcp-proxy would refuse to start with
is skipped with a warning.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import sys
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlsplit

import httpx

log = logging.getLogger("kifli.hosts")

SUPERVISOR = "http://supervisor"


def _supervisor(client: httpx.Client, path: str) -> dict:
    try:
        resp = client.get(f"{SUPERVISOR}{path}")
        resp.raise_for_status()
        return resp.json().get("data") or {}
    except (httpx.HTTPError, ValueError) as ex:
        log.warning("A Supervisor %s nem érhető el (%s) – az innen jövő hostnevek kimaradnak.", path, ex)
        return {}


def supervisor_hosts(client: httpx.Client) -> list[str]:
    """The names and addresses Home Assistant may use to reach the add-on."""
    hosts: list[str] = []
    if name := _supervisor(client, "/info").get("hostname"):
        hosts += [name, f"{name}.local"]
    addon = _supervisor(client, "/addons/self/info")
    hosts += [addon.get("hostname"), addon.get("ip_address")]
    # /network/info needs hassio_api (default role) in config.yaml
    for interface in _supervisor(client, "/network/info").get("interfaces") or []:
        for family in ("ipv4", "ipv6"):
            for address in (interface.get(family) or {}).get("address") or []:
                hosts.append(address.split("/", 1)[0])  # "192.168.1.10/24"
    return [host for host in hosts if host]


def configured_hosts(options: Path) -> list[str]:
    try:
        value = json.loads(options.read_text(encoding="utf-8")).get("allowed_hosts")
    except (OSError, ValueError):
        return []
    return [host for host in value if isinstance(host, str)] if isinstance(value, list) else []


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def _valid(authority: str) -> bool:
    """The same check mcp-proxy makes before it starts (it exits on an invalid entry)."""
    host = authority.removesuffix(":*")
    if (not host or host.endswith(":") or "*" in host or any(c in host for c in ",/@?#\\")
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in host)):
        return False
    try:
        parsed = urlsplit(f"//{host}")
        port = parsed.port
    except ValueError:
        return False
    return parsed.hostname is not None and parsed.netloc == host and (port is None or 1 <= port <= 65535)


def authorities(hosts: Iterable[str]) -> list[str]:
    """Each host with and without a port; any port, since the host port can be remapped."""
    result: list[str] = []
    for entry in hosts:
        host = entry.strip().lower()
        if "://" in host:  # a URL pasted from the MCP integration
            host = urlsplit(host).netloc
        if not host:
            continue
        if _is_ip(host) and ":" in host.strip("[]"):
            host = f"[{host.strip('[]')}]"
        has_port = host.rsplit("]", 1)[-1].count(":") == 1 if host.startswith("[") else ":" in host
        candidates = [host] if has_port else [host, f"{host}:*"]
        if not all(_valid(candidate) for candidate in candidates):
            log.warning("Érvénytelen hostnév az 'allowed_hosts'-ban, kihagyva: %r", entry)
            continue
        result += [candidate for candidate in candidates if candidate not in result]
    return result


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")
    hosts: list[str] = []
    if token := os.environ.get("SUPERVISOR_TOKEN"):
        with httpx.Client(headers={"Authorization": f"Bearer {token}"}, timeout=10) as client:
            hosts += supervisor_hosts(client)
    else:
        log.warning("Nincs SUPERVISOR_TOKEN – csak az 'allowed_hosts'-ban megadott hostnevek érik el az SSE-t.")
    hosts += configured_hosts(Path(os.environ.get("KIFLI_DATA_DIR", "/data")) / "options.json")
    for authority in authorities(hosts):
        print(authority)


if __name__ == "__main__":
    main()
