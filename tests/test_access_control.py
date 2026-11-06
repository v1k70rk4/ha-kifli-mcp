"""Who can use the Kifli access: logout, the ingress page's peers, the endpoint the token is for."""

from __future__ import annotations

import asyncio
import json
import socket
import time

import httpx
import kifli_auth
import pytest
import uvicorn
from kifli_auth import AuthManager, LoginCancelled, build_app
from mcp.server.fastmcp import FastMCP
from mcp.shared.auth import OAuthToken
from mcp_schema_shim import Upstream, ingress_server

MCP_URL = "https://mcp.kifli.hu/mcp"
AUTH_URL = "https://identity.kifli.hu/realms/kifli/protocol/openid-connect/auth?client_id=x"


def _signed_in(tmp_path, mcp_url: str = MCP_URL, **extra) -> None:
    oauth = tmp_path / "oauth"
    oauth.mkdir(exist_ok=True)
    tokens = {"access_token": "STORED-ACCESS", "token_type": "Bearer", "refresh_token": "STORED-REFRESH",
              "expires_at": time.time() + 3600, **extra}
    if mcp_url:
        tokens["mcp_url"] = mcp_url
    (oauth / "tokens.json").write_text(json.dumps(tokens), encoding="utf-8")
    (oauth / "client.json").write_text(json.dumps({"client_id": "C", "redirect_uris": ["http://localhost:3334/cb"]}),
                                       encoding="utf-8")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _serve(server: uvicorn.Server) -> asyncio.Task:
    task = asyncio.create_task(server.serve())
    while not server.started:
        assert not task.done(), "server did not start"
        await asyncio.sleep(0.05)
    return task


# --- logout --------------------------------------------------------------------------------------

def test_logout_ends_the_upstream_session_and_forgets_the_token(tmp_path):
    """Before the fix the session stayed open and the token in memory kept being sent."""
    mcp = FastMCP("fake-kifli")

    @mcp.tool()
    def ping() -> str:
        return "pong"

    seen: list[tuple[str, str | None]] = []
    app = mcp.streamable_http_app()

    async def recorder(scope, receive, send):
        if scope["type"] == "http":
            seen.append((scope["method"], dict(scope["headers"]).get(b"authorization", b"").decode() or None))
        await app(scope, receive, send)

    port = _free_port()
    url = f"http://127.0.0.1:{port}/mcp"
    _signed_in(tmp_path, url)

    async def scenario():
        server = uvicorn.Server(uvicorn.Config(recorder, host="127.0.0.1", port=port, log_level="warning"))
        served = await _serve(server)
        auth = AuthManager(url, tmp_path)
        upstream = Upstream(url, auth)
        running = asyncio.create_task(upstream.run())
        try:
            auth.logged_in.set()
            await asyncio.wait_for(upstream.ready.wait(), 10)
            assert (await upstream.session.call_tool("ping", {})).content[0].text == "pong"

            await auth.logout()

            assert upstream.session is None
            assert auth.provider.context.current_tokens is None
            assert not (tmp_path / "oauth" / "tokens.json").exists()
            # the session was ended at the server while the token was still known
            assert ("DELETE", "Bearer STORED-ACCESS") in seen
            await asyncio.sleep(0.5)
            assert upstream.session is None  # stays down until the next sign-in
        finally:
            running.cancel()
            server.should_exit = True
            await served

    asyncio.run(scenario())


def test_logout_abandons_a_sign_in_in_progress(tmp_path):
    auth = AuthManager(MCP_URL, tmp_path)

    async def scenario():
        await auth._on_redirect(AUTH_URL)
        waiting = asyncio.create_task(auth._wait_for_code())
        await asyncio.sleep(0)
        await auth.logout()
        with pytest.raises(LoginCancelled):
            await asyncio.wait_for(waiting, 5)  # before the fix it waited for a code forever

    asyncio.run(scenario())
    assert auth.status == "needs_login"
    assert auth.auth_url is None


def test_an_abandoned_sign_in_is_not_reported_as_an_error(tmp_path, monkeypatch):
    auth = AuthManager(MCP_URL, tmp_path)
    auth.status = "needs_login"

    async def cancelled() -> None:
        raise LoginCancelled("logged out")

    monkeypatch.setattr(auth, "ensure_logged_in", cancelled)
    asyncio.run(kifli_auth._safe_login(auth))
    assert auth.status == "needs_login"
    assert auth.error is None


# --- the ingress page accepts the Supervisor only ------------------------------------------------

async def _login_ok() -> str:
    return "ok"


@pytest.mark.parametrize("peer", ["172.30.33.5", "127.0.0.1", "192.168.1.10"])
@pytest.mark.parametrize(("method", "path"), [("GET", "/"), ("GET", "/status"), ("POST", "/logout")])
def test_page_rejects_other_peers(tmp_path, peer, method, path):
    _signed_in(tmp_path)
    auth = AuthManager(MCP_URL, tmp_path)
    app = build_app(auth, 42783, _login_ok)

    async def go():
        transport = httpx.ASGITransport(app=app, client=(peer, 50000))
        async with httpx.AsyncClient(transport=transport, base_url="http://ingress") as c:
            return await c.request(method, path, headers={"X-Forwarded-For": "172.30.32.2"})

    assert asyncio.run(go()).status_code == 403
    assert auth.storage.has_tokens()  # the logout did not happen


def test_the_real_server_ignores_a_forged_forwarded_header(tmp_path):
    # with uvicorn's proxy headers trusted from anyone, this header would make the request pass
    app = build_app(AuthManager(MCP_URL, tmp_path), 42783, _login_ok)
    port = _free_port()

    async def scenario():
        server = ingress_server(app, port)
        served = await _serve(server)
        try:
            async with httpx.AsyncClient() as c:
                resp = await c.get(f"http://127.0.0.1:{port}/status", headers={"X-Forwarded-For": "172.30.32.2"})
        finally:
            server.should_exit = True
            await served
        return resp.status_code

    assert asyncio.run(scenario()) == 403


# --- the token belongs to one MCP endpoint -------------------------------------------------------

def test_tokens_remember_their_endpoint_without_handing_it_to_the_sdk(tmp_path):
    auth = AuthManager(MCP_URL, tmp_path)
    asyncio.run(auth.storage.set_tokens(OAuthToken(access_token="a", token_type="Bearer")))
    assert auth.storage.tokens_mcp_url() == MCP_URL
    assert "mcp_url" not in asyncio.run(auth.storage.get_tokens()).model_dump()


def test_another_endpoint_needs_a_new_sign_in(tmp_path):
    _signed_in(tmp_path, MCP_URL)
    (tmp_path / "oauth" / "server.json").write_text("{}", encoding="utf-8")
    auth = AuthManager("https://mcp.rohlik.cz/mcp", tmp_path)  # country changed hu → cz
    assert not auth.storage.has_tokens()
    assert not (tmp_path / "oauth" / "client.json").exists()
    assert not (tmp_path / "oauth" / "server.json").exists()


@pytest.mark.parametrize("saved_for", [MCP_URL, None], ids=["same-endpoint", "saved-before-2.2.1"])
def test_the_same_endpoint_keeps_the_sign_in(tmp_path, saved_for):
    _signed_in(tmp_path, saved_for)
    auth = AuthManager(MCP_URL, tmp_path)
    assert auth.storage.has_tokens()
