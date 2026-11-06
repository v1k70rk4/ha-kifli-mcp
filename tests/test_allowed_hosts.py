"""The Host names the SSE endpoint accepts (mcp-proxy >= 0.13.3 answers 421 to any other).

Upgrading mcp-proxy from 0.11 to 0.14 (#7) passed every other test, but the add-on
would have rejected Home Assistant's requests to http://<ha-ip>:42783/sse. The last
tests here start the real mcp-proxy, so a change in its Host check fails them.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import allowed_hosts
import httpx
import pytest
from allowed_hosts import authorities, configured_hosts, supervisor_hosts

APP = Path(__file__).resolve().parents[1] / "kifli_mcp_connector" / "rootfs" / "app"

SUPERVISOR_DATA = {
    "/info": {"hostname": "homeassistant"},
    "/addons/self/info": {"hostname": "a0d7b954-kifli-mcp-connector", "ip_address": "172.30.33.5"},
    "/network/info": {"interfaces": [
        {"interface": "end0", "ipv4": {"address": ["192.168.1.10/24"]},
         "ipv6": {"address": ["fe80::1234/64", "2001:db8::5/64"]}},
        {"interface": "wlan0", "ipv4": {"address": []}, "ipv6": None},
    ]},
}


def _supervisor(data: dict, failing: frozenset[str] = frozenset()) -> httpx.Client:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["authorization"] == "Bearer TOKEN"
        if req.url.path in failing:
            return httpx.Response(403, json={"result": "error", "message": "missing API permission"})
        return httpx.Response(200, json={"result": "ok", "data": data[req.url.path]})

    return httpx.Client(transport=httpx.MockTransport(handler), headers={"Authorization": "Bearer TOKEN"})


def test_supervisor_hosts_cover_the_ways_home_assistant_reaches_the_add_on():
    with _supervisor(SUPERVISOR_DATA) as client:
        assert supervisor_hosts(client) == [
            "homeassistant", "homeassistant.local",
            "a0d7b954-kifli-mcp-connector", "172.30.33.5",
            "192.168.1.10", "fe80::1234", "2001:db8::5",
        ]


def test_a_failing_supervisor_endpoint_drops_only_its_own_hosts():
    # e.g. /network/info without hassio_api
    with _supervisor(SUPERVISOR_DATA, failing=frozenset({"/network/info"})) as client:
        assert supervisor_hosts(client) == [
            "homeassistant", "homeassistant.local", "a0d7b954-kifli-mcp-connector", "172.30.33.5"]


@pytest.mark.parametrize(("entry", "expected"), [
    pytest.param("192.168.1.10", ["192.168.1.10", "192.168.1.10:*"], id="ipv4"),
    pytest.param("fe80::1", ["[fe80::1]", "[fe80::1]:*"], id="ipv6"),
    pytest.param("[2001:db8::5]", ["[2001:db8::5]", "[2001:db8::5]:*"], id="bracketed-ipv6"),
    pytest.param("HomeAssistant.Local", ["homeassistant.local", "homeassistant.local:*"], id="case"),
    pytest.param(" mcp.example.com ", ["mcp.example.com", "mcp.example.com:*"], id="whitespace"),
    pytest.param("mcp.example.com:8443", ["mcp.example.com:8443"], id="with-port"),
    pytest.param("[::1]:8080", ["[::1]:8080"], id="ipv6-with-port"),
    pytest.param("http://192.168.1.10:42783/sse", ["192.168.1.10:42783"], id="pasted-url"),
])
def test_authorities(entry, expected):
    assert authorities([entry]) == expected


@pytest.mark.parametrize("entry", ["", "bad host", "a,b", "user@host", "host:99999", "host:abc", "host:"])
def test_invalid_entries_are_skipped(entry):
    assert authorities([entry, "ok.example"]) == ["ok.example", "ok.example:*"]


def test_duplicates_are_listed_once():
    assert authorities(["homeassistant", "HOMEASSISTANT", "homeassistant"]) == ["homeassistant", "homeassistant:*"]


def test_configured_hosts_come_from_the_add_on_options(tmp_path):
    options = tmp_path / "options.json"
    options.write_text(json.dumps({"port": 42783, "allowed_hosts": ["mcp.example.com", 5]}), encoding="utf-8")
    assert configured_hosts(options) == ["mcp.example.com"]
    assert configured_hosts(tmp_path / "missing.json") == []
    options.write_text(json.dumps({"allowed_hosts": "mcp.example.com"}), encoding="utf-8")
    assert configured_hosts(options) == []


def test_the_script_prints_the_configured_hosts_without_a_supervisor(tmp_path):
    (tmp_path / "options.json").write_text(json.dumps({"allowed_hosts": ["mcp.example.com"]}), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "SUPERVISOR_TOKEN"}
    env |= {"KIFLI_DATA_DIR": str(tmp_path), "PYTHONUTF8": "1"}  # the add-on runs with LANG=C.UTF-8
    res = subprocess.run([sys.executable, str(APP / "allowed_hosts.py")], env=env, capture_output=True,
                         text=True, encoding="utf-8", timeout=30, check=False)
    assert res.returncode == 0, res.stderr
    assert res.stdout.splitlines() == ["mcp.example.com", "mcp.example.com:*"]
    assert "SUPERVISOR_TOKEN" in res.stderr


# --- against the real mcp-proxy ------------------------------------------------------------------

PARITY_CASES = ["192.168.1.10", "192.168.1.10:*", "[fe80::1]:*", "homeassistant.local:8123", "host",
                "bad host", "a,b", "host:99999", "host:", "user@host", "[fe80::1", "host:*:*", "*"]


@pytest.mark.parametrize("authority", PARITY_CASES)
def test_our_check_matches_mcp_proxy(authority):
    # mcp-proxy exits at startup on an entry it considers invalid, so ours must not let one through
    from mcp_proxy.mcp_server import _valid_authority

    assert allowed_hosts._valid(authority) == _valid_authority(authority, allow_wildcard_port=True)


SERVER = """
from mcp.server.fastmcp import FastMCP

app = FastMCP("test")


@app.tool()
def ping() -> str:
    return "pong"


app.run()
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def proxy(tmp_path_factory):
    """mcp-proxy started the way the run script starts it, with the Supervisor's hosts allowed."""
    with _supervisor(SUPERVISOR_DATA) as client:
        hosts = authorities([*supervisor_hosts(client), "mcp.example.com"])
    server = tmp_path_factory.mktemp("proxy") / "server.py"
    server.write_text(SERVER, encoding="utf-8")
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "mcp_proxy", "--host=0.0.0.0", f"--port={port}", "--pass-environment",
         *(f"--allowed-host={host}" for host in hosts), "--", sys.executable, str(server)],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 30
        while True:
            assert proc.poll() is None, f"mcp-proxy exited: {proc.stderr.read()}"
            try:
                httpx.get(f"http://127.0.0.1:{port}/status", timeout=1)
                break
            except httpx.TransportError:
                assert time.monotonic() < deadline, "mcp-proxy did not start"
                time.sleep(0.2)
        yield port
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def _sse_status(port: int, host: str) -> int:
    with httpx.stream("GET", f"http://127.0.0.1:{port}/sse", headers={"Host": host}, timeout=5) as resp:
        return resp.status_code


@pytest.mark.parametrize("host", [
    "192.168.1.10:42783", "192.168.1.10:8000", "[2001:db8::5]:42783", "homeassistant.local:42783",
    "a0d7b954-kifli-mcp-connector:42783", "172.30.33.5:42783", "mcp.example.com:42783",
])
def test_mcp_proxy_accepts_the_hosts_home_assistant_uses(proxy, host):
    assert _sse_status(proxy, host) == 200


def test_mcp_proxy_still_rejects_other_hosts(proxy):
    assert _sse_status(proxy, "evil.example:42783") == 421
