"""Staying signed in across add-on restarts (update, Home Assistant reboot).

A fake Rohlik Group MCP server and identity server answer the requests. Before
the fix the SDK sent the expired access token after a restart, got a 401 and
started a full sign-in, instead of using the refresh token it had.
"""

from __future__ import annotations

import asyncio
import json
import time
from urllib.parse import parse_qs

import httpx
import pytest
from kifli_auth import AuthManager, KifliOAuthProvider
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientInformationFull

MCP = "https://mcp.kifli.hu/mcp"
AS = "https://identity.kifli.hu/realms/kifli"


class FakeKifli:
    """The MCP endpoint accepts only the current access token; the identity server refreshes."""

    def __init__(self, refresh_ok: bool = True, discovery_ok: bool = True) -> None:
        self.refresh_ok = refresh_ok
        self.discovery_ok = discovery_ok
        self.valid_token = "NEW-ACCESS"
        self.calls: list[str] = []
        self.discovery_requests = 0

    def __call__(self, req: httpx.Request) -> httpx.Response:
        url = str(req.url).split("?")[0]
        if url == MCP:
            self.calls.append(f"mcp {req.headers.get('authorization')}")
            if req.headers.get("authorization") == f"Bearer {self.valid_token}":
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": 0, "result": {}})
            return httpx.Response(401, headers={
                "WWW-Authenticate": 'Bearer resource_metadata="https://mcp.kifli.hu/.well-known/oauth-protected-resource/mcp"'})
        if "oauth-protected-resource" in url:
            self.discovery_requests += 1
            if not self.discovery_ok:
                return httpx.Response(404)
            return httpx.Response(200, json={"resource": MCP, "authorization_servers": [AS]})
        if "openid-configuration" in url or "oauth-authorization-server" in url:
            self.discovery_requests += 1
            return httpx.Response(200, json={
                "issuer": AS, "authorization_endpoint": f"{AS}/auth", "token_endpoint": f"{AS}/token",
                "registration_endpoint": f"{AS}/register", "response_types_supported": ["code"],
                "code_challenge_methods_supported": ["S256"],
                "grant_types_supported": ["authorization_code", "refresh_token"]})
        if url == f"{AS}/token":
            form = parse_qs(req.content.decode())
            self.calls.append(f"token {form.get('grant_type', [''])[0]}")
            if (self.refresh_ok and form.get("grant_type") == ["refresh_token"]
                    and form.get("refresh_token") == ["STORED-REFRESH"] and form.get("client_id") == ["STORED-CLIENT"]):
                return httpx.Response(200, json={"access_token": "NEW-ACCESS", "token_type": "Bearer",
                                                 "expires_in": 300, "refresh_token": "NEW-REFRESH"})
            return httpx.Response(400, json={"error": "invalid_grant"})
        self.calls.append(f"other {req.method} {url}")
        return httpx.Response(404)


def _stored_sign_in(tmp_path, *, expires_at: float | None) -> None:
    """What a signed-in add-on has in /data/oauth (expires_at None: saved by a version before 2.1.2)."""
    oauth = tmp_path / "oauth"
    oauth.mkdir()
    tokens = {"access_token": "STORED-ACCESS", "token_type": "Bearer", "expires_in": 300,
              "refresh_token": "STORED-REFRESH", "scope": "openid email roles offline_access"}
    if expires_at is not None:
        tokens["expires_at"] = expires_at
    (oauth / "tokens.json").write_text(json.dumps(tokens), encoding="utf-8")
    client = OAuthClientInformationFull(
        client_id="STORED-CLIENT", redirect_uris=["http://localhost:3334/oauth/callback"],
        grant_types=["authorization_code", "refresh_token"], response_types=["code"],
        token_endpoint_auth_method="none")
    (oauth / "client.json").write_text(client.model_dump_json(exclude_none=True), encoding="utf-8")


def _first_request_after_restart(tmp_path, server: FakeKifli, discovery=None) -> tuple[AuthManager, httpx.Response | None]:
    auth = AuthManager(MCP, tmp_path)  # a fresh process: nothing in memory, only /data
    auth.provider.discovery_transport = httpx.MockTransport(discovery or server)

    async def go():
        async with httpx.AsyncClient(auth=auth.provider, transport=httpx.MockTransport(server), timeout=5) as c:
            return await c.post(MCP, json={"jsonrpc": "2.0", "id": 0, "method": "ping"})

    async def bounded():
        try:
            return await asyncio.wait_for(go(), 3)
        except TimeoutError:
            return None  # the provider is waiting for a browser sign-in

    return auth, asyncio.run(bounded())


@pytest.mark.parametrize("expires_at", [time.time() - 60, None], ids=["expired", "saved-by-older-version"])
def test_restart_refreshes_the_token_instead_of_signing_in_again(tmp_path, expires_at):
    _stored_sign_in(tmp_path, expires_at=expires_at)
    server = FakeKifli()
    auth, resp = _first_request_after_restart(tmp_path, server)
    assert auth.auth_url is None, f"asked for a new sign-in: {server.calls}"
    assert resp is not None and resp.status_code == 200
    assert server.calls == ["token refresh_token", "mcp Bearer NEW-ACCESS"]
    saved = json.loads((tmp_path / "oauth" / "tokens.json").read_text(encoding="utf-8"))
    assert saved["access_token"] == "NEW-ACCESS"
    assert saved["refresh_token"] == "NEW-REFRESH"
    assert saved["expires_at"] == pytest.approx(time.time() + 300, abs=30)


def test_restart_with_a_valid_token_uses_it_directly(tmp_path):
    _stored_sign_in(tmp_path, expires_at=time.time() + 120)
    server = FakeKifli()
    server.valid_token = "STORED-ACCESS"
    _auth, resp = _first_request_after_restart(tmp_path, server)
    assert resp is not None and resp.status_code == 200
    assert server.calls == ["mcp Bearer STORED-ACCESS"]  # no needless refresh


def test_rejected_refresh_token_asks_for_a_new_sign_in(tmp_path):
    _stored_sign_in(tmp_path, expires_at=time.time() - 60)
    server = FakeKifli(refresh_ok=False)
    auth, resp = _first_request_after_restart(tmp_path, server)
    assert resp is None
    assert auth.auth_url is not None  # a real sign-in is the only way left


def test_token_expiry_is_saved_but_not_handed_to_the_sdk(tmp_path):
    auth = AuthManager(MCP, tmp_path)
    from mcp.shared.auth import OAuthToken

    asyncio.run(auth.storage.set_tokens(OAuthToken(access_token="a", expires_in=300, refresh_token="r")))
    assert auth.storage.expires_at() == pytest.approx(time.time() + 300, abs=30)
    token = asyncio.run(auth.storage.get_tokens())
    assert token.access_token == "a"
    assert "expires_at" not in token.model_dump()


def test_the_sdk_still_has_the_private_hooks_we_override():
    # KifliOAuthProvider overrides private SDK methods; an mcp update that renames them would make
    # the overrides silently dead code (no offline_access, logged out after every restart)
    for name in ("_initialize", "_perform_authorization_code_grant"):
        assert name in vars(OAuthClientProvider), f"OAuthClientProvider.{name} is gone – check KifliOAuthProvider"
        assert name in vars(KifliOAuthProvider)


def _server_metadata() -> dict:
    return {"issuer": AS, "authorization_endpoint": f"{AS}/auth", "token_endpoint": f"{AS}/token",
            "response_types_supported": ["code"]}


def test_refresh_saves_the_server_metadata_for_the_next_restart(tmp_path):
    _stored_sign_in(tmp_path, expires_at=None)
    _first_request_after_restart(tmp_path, FakeKifli())
    saved = json.loads((tmp_path / "oauth" / "server.json").read_text(encoding="utf-8"))
    assert saved["token_endpoint"] == f"{AS}/token"


def test_restart_uses_the_saved_server_metadata_without_discovery(tmp_path):
    _stored_sign_in(tmp_path, expires_at=time.time() - 60)
    (tmp_path / "oauth" / "server.json").write_text(json.dumps(_server_metadata()), encoding="utf-8")
    server = FakeKifli(discovery_ok=False)  # discovery would fail: the saved metadata must be enough
    auth, resp = _first_request_after_restart(tmp_path, server)
    assert auth.auth_url is None
    assert resp is not None and resp.status_code == 200
    assert server.discovery_requests == 0


def test_failed_discovery_falls_back_to_signing_in_as_before(tmp_path):
    # only our startup lookup fails (e.g. a network hiccup); the SDK's own flow then works as before
    _stored_sign_in(tmp_path, expires_at=None)
    auth, resp = _first_request_after_restart(tmp_path, FakeKifli(), discovery=lambda _req: httpx.Response(503))
    assert resp is None
    assert auth.auth_url is not None


def test_metadata_from_another_issuer_is_not_used(tmp_path):
    _stored_sign_in(tmp_path, expires_at=None)
    server = FakeKifli()
    real = server.__call__

    def other_issuer(req: httpx.Request) -> httpx.Response:
        resp = real(req)
        if "openid-configuration" in str(req.url) or "oauth-authorization-server" in str(req.url):
            data = json.loads(resp.content)
            data["issuer"] = "https://evil.example/realms/kifli"
            return httpx.Response(200, json=data)
        return resp

    auth = AuthManager(MCP, tmp_path)
    auth.provider.discovery_transport = httpx.MockTransport(other_issuer)
    assert asyncio.run(auth.provider._discover_server_metadata()) is None


def test_logout_removes_the_server_metadata(tmp_path):
    _stored_sign_in(tmp_path, expires_at=None)
    _first_request_after_restart(tmp_path, FakeKifli())
    auth = AuthManager(MCP, tmp_path)
    asyncio.run(auth.logout())
    assert not (tmp_path / "oauth" / "server.json").exists()
    assert not auth.storage.has_tokens()
