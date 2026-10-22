"""A bejelentkező (ingress) oldal, a bemásolt OAuth-visszahívás és a tokentárolás."""

from __future__ import annotations

import asyncio
import stat
import sys

import httpx
import pytest
from kifli_auth import AuthManager, FileTokenStorage, build_app
from mcp.shared.auth import OAuthToken

MCP_URL = "https://mcp.kifli.hu/mcp"
AUTH_URL = "https://identity.kifli.hu/realms/kifli/protocol/openid-connect/auth?client_id=x"
CALLBACK = "http://localhost:3334/oauth/callback?code=abc&state=xyz"


@pytest.fixture
def auth(tmp_path):
    return AuthManager(MCP_URL, tmp_path)


async def _login_ok() -> str:
    return "MCP :42783 → 200"


def _client(auth: AuthManager) -> httpx.AsyncClient:
    app = build_app(auth, 42783, _login_ok)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ingress")


# --- a bemásolt átirányítási cím ----------------------------------------------------------------

@pytest.mark.parametrize(("pasted", "expected"), [
    ("", "Üres mező"),
    ("   ", "Üres mező"),
    ("http://localhost:3334/oauth/callback?state=xyz", "nincs 'code'"),
    ("http://localhost:3334/oauth/callback?error=access_denied&error_description=nope", "access_denied nope"),
])
def test_invalid_callback_urls_are_rejected(auth, pasted, expected):
    async def scenario():
        await auth._on_redirect(AUTH_URL)
        return auth.submit_callback_url(pasted)

    assert expected in asyncio.run(scenario())


def test_callback_without_login_in_progress_is_rejected(auth):
    assert "nincs folyamatban" in auth.submit_callback_url(CALLBACK)


@pytest.mark.parametrize("pasted", [CALLBACK, "code=abc&state=xyz", "?code=abc&state=xyz", f"  {CALLBACK}\n"])
def test_callback_url_delivers_code_and_state(auth, pasted):
    async def scenario():
        await auth._on_redirect(AUTH_URL)
        assert auth.status == "waiting_code"
        assert auth.submit_callback_url(pasted) is None
        code_state = await auth._wait_for_code()
        # ugyanaz a cím másodszor már nem fogadható el
        return code_state, auth.status, auth.submit_callback_url(pasted)

    code_state, status, second = asyncio.run(scenario())
    assert code_state == ("abc", "xyz")
    assert status == "exchanging"
    assert "nincs folyamatban" in second


# --- az ingress oldal ---------------------------------------------------------------------------

def test_start_page_and_status_before_login(auth):
    async def scenario():
        async with _client(auth) as c:
            return await c.get("/"), await c.get("/status")

    page, status = asyncio.run(scenario())
    assert page.status_code == 200
    assert 'action="start"' in page.text
    assert status.json() == {"status": "init", "error": None, "logged_in": False}


def test_full_login_via_pasted_url(auth):
    async def fake_sdk():
        # amit az SDK tesz: megvárja a kódot, kicseréli tokenre, kész
        await auth._wait_for_code()
        auth.status = "ok"
        auth.logged_in.set()

    async def scenario():
        await auth._on_redirect(AUTH_URL)
        sdk = asyncio.create_task(fake_sdk())
        async with _client(auth) as c:
            waiting = await c.get("/")
            done = await c.post("/callback", data={"url": CALLBACK})
        await sdk
        return waiting, done

    waiting, done = asyncio.run(scenario())
    assert AUTH_URL.replace("&", "&amp;") in waiting.text  # a bejelentkező link escape-elve
    assert done.status_code == 200
    assert "Siker!" in done.text
    assert "MCP :42783 → 200" in done.text
    assert 'action="logout"' in done.text


def test_error_from_identity_server_is_html_escaped(auth):
    evil = "http://localhost:3334/oauth/callback?error=%3Cscript%3Ealert(1)%3C/script%3E"

    async def scenario():
        async with _client(auth) as c:
            return await c.post("/callback", data={"url": evil})

    resp = asyncio.run(scenario())
    assert "<script>alert(1)</script>" not in resp.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in resp.text


def test_logout_clears_tokens(auth):
    async def scenario():
        await auth.storage.set_tokens(OAuthToken(access_token="a", token_type="Bearer", refresh_token="r"))
        auth.status = "ok"
        auth.logged_in.set()
        async with _client(auth) as c:
            resp = await c.post("/logout")
        return resp

    resp = asyncio.run(scenario())
    assert resp.status_code == 303
    assert not auth.storage.has_tokens()
    assert auth.status == "needs_login"
    assert not auth.logged_in.is_set()


# --- tokentárolás -------------------------------------------------------------------------------

def test_token_storage_roundtrip_and_clear(tmp_path):
    storage = FileTokenStorage(tmp_path / "oauth")

    async def scenario():
        assert await storage.get_tokens() is None
        await storage.set_tokens(OAuthToken(access_token="a", token_type="Bearer", refresh_token="r"))
        return await storage.get_tokens()

    tokens = asyncio.run(scenario())
    assert (tokens.access_token, tokens.refresh_token) == ("a", "r")
    storage.clear()
    assert not storage.has_tokens()
    storage.clear()  # a hiányzó fájl sem hiba


def test_corrupt_token_file_reads_as_logged_out(tmp_path):
    storage = FileTokenStorage(tmp_path / "oauth")
    (tmp_path / "oauth" / "tokens.json").write_text("{nem json", encoding="utf-8")
    assert asyncio.run(storage.get_tokens()) is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX jogosultság")
def test_token_file_is_private(tmp_path):
    storage = FileTokenStorage(tmp_path / "oauth")
    asyncio.run(storage.set_tokens(OAuthToken(access_token="a", token_type="Bearer")))
    mode = stat.S_IMODE((tmp_path / "oauth" / "tokens.json").stat().st_mode)
    assert mode == 0o600
