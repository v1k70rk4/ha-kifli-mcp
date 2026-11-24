"""A new sign-in that the running add-on needs, not the one at start.

When the identity server rejects the refresh token while the add-on runs, the SDK starts the
sign-in inside the request that needed the token (the upstream session's), not in
AuthManager.ensure_logged_in. Before the fix the page then stuck at "exchanging token" with the
old sign-in link although the sign-in had worked, every further paste answered "No login in
progress", the start button never came back, and every tool request waited for the sign-in.
"""

from __future__ import annotations

import asyncio
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from kifli_auth import AuthManager, build_app
from test_oauth_restart import MCP, FakeKifli, _stored_sign_in

SUPERVISOR = ("172.30.32.2", 50000)


class FakeKifliSignIn(FakeKifli):
    """Rejects the stored refresh token; exchanges the code CODE for a new access token."""

    def __init__(self, code_ok: bool = True) -> None:
        super().__init__(refresh_ok=False)
        self.code_ok = code_ok

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if str(req.url).split("?")[0].endswith("/token"):
            form = parse_qs(req.content.decode())
            if form.get("grant_type") == ["authorization_code"]:
                self.calls.append("token authorization_code")
                if self.code_ok and form.get("code") == ["CODE"]:
                    return httpx.Response(200, json={"access_token": "NEW-ACCESS", "token_type": "Bearer",
                                                     "expires_in": 300, "refresh_token": "NEW-REFRESH"})
                return httpx.Response(400, json={"error": "invalid_grant"})
        return super().__call__(req)


def _running_add_on(tmp_path) -> AuthManager:
    """Signed in at start; the access token has expired since."""
    _stored_sign_in(tmp_path, expires_at=time.time() - 60)
    auth = AuthManager(MCP, tmp_path)
    auth.status = "ok"
    auth.logged_in.set()
    return auth


async def _wait_until(cond, what: str) -> None:
    for _ in range(100):
        if cond():
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


class Scenario:
    def __init__(self, tmp_path, server: FakeKifli) -> None:
        self.auth = _running_add_on(tmp_path)
        self.auth.provider.discovery_transport = httpx.MockTransport(server)
        self.server = server
        self.reloads = 0
        # the Home Assistant notification: recorded, never sent to a Supervisor
        self.notifications: list[bool] = []

        async def notify(needed: bool) -> bool:
            self.notifications.append(needed)
            return True

        self.auth.notify_ha = notify

        async def on_login_ok() -> str:
            self.reloads += 1
            return "reloaded"

        self.app = build_app(self.auth, 42783, on_login_ok)

    async def upstream_request(self) -> httpx.Response:
        """A request of the running upstream session, through the same OAuth provider."""
        async with httpx.AsyncClient(auth=self.auth.provider, transport=httpx.MockTransport(self.server),
                                     timeout=5) as c:
            return await c.post(MCP, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    async def page(self, method: str = "GET", path: str = "/", **kw) -> str:
        transport = httpx.ASGITransport(app=self.app, client=SUPERVISOR)
        async with httpx.AsyncClient(transport=transport, base_url="http://ingress") as c:
            resp = await c.request(method, path, **kw)
            if resp.status_code == 303:
                resp = await c.get("/")
            return resp.text

    def pasted(self, state: str | None = None) -> dict:
        state = state or parse_qs(urlsplit(self.auth.auth_url).query)["state"][0]
        return {"url": f"http://localhost:3334/oauth/callback?code=CODE&state={state}"}


def test_a_sign_in_needed_while_running_completes_on_the_page(tmp_path):
    s = Scenario(tmp_path, FakeKifliSignIn())

    async def go():
        request = asyncio.create_task(s.upstream_request())
        await _wait_until(lambda: s.auth.status == "waiting_code", "the sign-in link")
        # the tools are not offered meanwhile, so Home Assistant does not wait for the sign-in
        assert not s.auth.logged_in.is_set()
        assert s.auth.auth_url in (await s.page()).replace("&amp;", "&")

        after = await s.page("POST", "/callback", data=s.pasted())
        resp = await asyncio.wait_for(request, 5)
        return after, resp

    after, resp = asyncio.run(go())
    assert "Bejelentkezve" in after, after  # before the fix: the sign-in page again, "exchanging token"
    assert s.auth.status == "ok"
    assert s.auth.logged_in.is_set()
    assert s.auth.auth_url is None
    assert s.reloads == 1  # Home Assistant is told to reload the tools
    assert resp.status_code == 200  # the request that needed the sign-in went through with the new token
    assert s.server.calls[-1] == "mcp Bearer NEW-ACCESS"
    assert s.notifications == [True, False]  # "sign in" shown, then dismissed


def test_a_link_from_an_earlier_sign_in_is_refused_and_the_sign_in_goes_on(tmp_path):
    s = Scenario(tmp_path, FakeKifliSignIn())

    async def go():
        request = asyncio.create_task(s.upstream_request())
        await _wait_until(lambda: s.auth.status == "waiting_code", "the sign-in link")
        refused = await s.page("POST", "/callback", data=s.pasted(state="OLD-STATE"))
        assert s.auth.status == "waiting_code"  # the SDK would have ended the sign-in on this
        assert s.server.calls.count("token authorization_code") == 0
        ok = await s.page("POST", "/callback", data=s.pasted())
        await asyncio.wait_for(request, 5)
        return refused, ok

    refused, ok = asyncio.run(go())
    assert "korábbi bejelentkezéshez" in refused
    assert "Bejelentkezve" in ok


def test_a_failed_token_exchange_offers_a_new_sign_in(tmp_path):
    s = Scenario(tmp_path, FakeKifliSignIn(code_ok=False))

    async def go():
        request = asyncio.create_task(s.upstream_request())
        await _wait_until(lambda: s.auth.status == "waiting_code", "the sign-in link")
        after = await s.page("POST", "/callback", data=s.pasted())
        with pytest.raises(Exception):  # noqa: B017 – whatever the SDK raises, the request fails
            await asyncio.wait_for(request, 5)
        return after

    after = asyncio.run(go())
    assert s.auth.status == "error"
    assert "invalid_grant" in (s.auth.error or "")
    assert not s.auth.logged_in.is_set()
    # the button that starts a new sign-in, not the link of the one that failed (before: stuck at "exchanging")
    assert 'action="start"' in after
    assert "identity.kifli.hu/realms/kifli/auth" not in after


def test_the_start_button_starts_a_new_sign_in_after_a_failed_one(tmp_path, monkeypatch):
    s = Scenario(tmp_path, FakeKifliSignIn(code_ok=False))
    real_client = httpx.AsyncClient

    def client(**kw):  # ensure_logged_in's own client talks to the fake server too
        kw.setdefault("transport", httpx.MockTransport(s.server))
        return real_client(**kw)

    monkeypatch.setattr(httpx, "AsyncClient", client)

    async def go():
        request = asyncio.create_task(s.upstream_request())
        await _wait_until(lambda: s.auth.status == "waiting_code", "the sign-in link")
        first = s.auth.auth_url
        await s.page("POST", "/callback", data=s.pasted())
        with pytest.raises(Exception):  # noqa: B017
            await asyncio.wait_for(request, 5)

        s.server.code_ok = True
        page = await s.page("POST", "/start")
        assert s.auth.status == "waiting_code"
        assert s.auth.auth_url and s.auth.auth_url != first
        assert s.auth.auth_url in page.replace("&amp;", "&")
        return await s.page("POST", "/callback", data=s.pasted())

    ok = asyncio.run(go())
    assert "Bejelentkezve" in ok
    assert s.auth.status == "ok"
    assert s.auth.logged_in.is_set()
    assert s.reloads == 1


def test_a_logout_during_a_running_sign_in_is_not_undone_by_it(tmp_path):
    s = Scenario(tmp_path, FakeKifliSignIn())

    async def go():
        request = asyncio.create_task(s.upstream_request())
        await _wait_until(lambda: s.auth.status == "waiting_code", "the sign-in link")
        await s.auth.logout()
        with pytest.raises(Exception):  # noqa: B017
            await asyncio.wait_for(request, 5)

    asyncio.run(go())
    assert s.auth.status == "needs_login"
    assert not s.auth.logged_in.is_set()
    assert not s.auth.storage.has_tokens()


def test_a_token_request_that_fails_on_the_wire_offers_a_new_sign_in(tmp_path):
    # httpx raises the timeout and only closes the flow: no token response to report the end
    server = FakeKifliSignIn()

    def timing_out(req: httpx.Request) -> httpx.Response:
        if "authorization_code" in req.content.decode(errors="replace"):
            raise httpx.ReadTimeout("token endpoint timed out", request=req)
        return server(req)

    s = Scenario(tmp_path, server)
    s.upstream_request = lambda: _request_through(s, timing_out)

    async def go():
        request = asyncio.create_task(s.upstream_request())
        await _wait_until(lambda: s.auth.status == "waiting_code", "the sign-in link")
        await s.page("POST", "/callback", data=s.pasted())
        with pytest.raises(httpx.ReadTimeout):
            await asyncio.wait_for(request, 5)
        return await s.page()

    page = asyncio.run(go())
    assert s.auth.status == "error"  # before: "exchanging" for good, /start refused
    assert "megszakadt" in (s.auth.error or "")
    assert 'action="start"' in page


def test_tokens_of_an_exchange_a_logout_overtook_are_not_saved(tmp_path):
    server = FakeKifliSignIn()
    s = Scenario(tmp_path, server)

    async def logout_meanwhile(req: httpx.Request) -> httpx.Response:
        if "authorization_code" in req.content.decode(errors="replace"):
            await s.auth.logout()  # while the token request is on its way
        return server(req)

    s.upstream_request = lambda: _request_through(s, logout_meanwhile)

    async def go():
        request = asyncio.create_task(s.upstream_request())
        await _wait_until(lambda: s.auth.status == "waiting_code", "the sign-in link")
        await s.page("POST", "/callback", data=s.pasted())
        with pytest.raises(Exception):  # noqa: B017
            await asyncio.wait_for(request, 5)

    asyncio.run(go())
    assert "token authorization_code" in server.calls  # the identity server did answer with tokens
    assert not s.auth.storage.has_tokens()  # before: written to /data after the logout
    assert s.auth.provider.context.current_tokens is None
    assert s.auth.status == "needs_login"
    assert not s.auth.logged_in.is_set()


async def _request_through(s: Scenario, handler) -> httpx.Response:
    async with httpx.AsyncClient(auth=s.auth.provider, transport=httpx.MockTransport(handler), timeout=5) as c:
        return await c.post(MCP, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
