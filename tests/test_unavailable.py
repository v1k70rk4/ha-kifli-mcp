"""Assist keeps working while the Kifli MCP cannot be reached.

Home Assistant's MCP integration gives a tool listing 30 s; one that fails or does not arrive in
time fails its setup, its LLM API is gone, and every Assist conversation using it fails. So the
shim answers the listing in time, from the last list it saw if needed, and a call answers that
Kifli is unavailable, which the assistant can pass on.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import kifli_auth
import mcp_schema_shim
import pytest
from kifli_auth import AuthManager
from mcp import types
from mcp_schema_shim import ToolCache, Upstream, build_server
from tool_settings import ToolSettings

MCP_URL = "https://mcp.kifli.hu/mcp"
PING = types.Tool(name="get_cart", description="A kosár tartalma.",
                  inputSchema={"type": "object", "properties": {}})


class FakeSession:
    """The upstream ClientSession: answers, fails, or hangs until released."""

    def __init__(self) -> None:
        self.mode = "ok"
        self.release = asyncio.Event()
        self.finished: list[str] = []

    async def _answer(self, what: str, result):
        if self.mode == "hang":
            await self.release.wait()
        if self.mode == "fail":
            raise RuntimeError("upstream broke")
        self.finished.append(what)
        return result

    async def list_tools(self):
        return await self._answer("list", types.ListToolsResult(tools=[PING]))

    async def call_tool(self, name, args):
        return await self._answer(f"call {name}", types.CallToolResult(
            content=[types.TextContent(type="text", text="2 tétel")]))


class Shim:
    def __init__(self, tmp_path, *, logged_in: bool = True, session: bool = True) -> None:
        self.auth = AuthManager(MCP_URL, tmp_path)
        if logged_in:
            self.auth.logged_in.set()
        self.upstream = Upstream(MCP_URL, self.auth)
        self.fake = FakeSession()
        if session:
            self.upstream.session = self.fake
        self.cache = ToolCache(tmp_path / "tools_cache.json")
        settings = ToolSettings(tmp_path / "tool_settings.json", new_tools_enabled=True)
        self.server = build_server(self.auth, self.upstream, settings, self.cache)

    async def list(self) -> list[str]:
        res = await self.server.request_handlers[types.ListToolsRequest](types.ListToolsRequest(method="tools/list"))
        return [t.name for t in res.root.tools]

    async def call(self, name: str = "get_cart") -> types.CallToolResult:
        req = types.CallToolRequest(method="tools/call", params=types.CallToolRequestParams(name=name, arguments={}))
        return (await self.server.request_handlers[types.CallToolRequest](req)).root


def _text(result: types.CallToolResult) -> str:
    return " ".join(c.text for c in result.content if isinstance(c, types.TextContent))


def _seen_once(tmp_path) -> None:
    """A signed-in run listed the tools once: the list is saved."""
    async def go():
        assert await Shim(tmp_path).list() == ["get_cart"]
    asyncio.run(go())


# --- the tool listing ----------------------------------------------------------------------------

def test_the_listing_is_saved_and_offered_while_a_sign_in_is_needed(tmp_path):
    _seen_once(tmp_path)
    saved = json.loads((tmp_path / "tools_cache.json").read_text(encoding="utf-8"))
    assert [t["name"] for t in saved["tools"]] == ["get_cart"]

    async def go():
        shim = Shim(tmp_path, logged_in=False)  # also after a restart: the list comes from /data
        names = await shim.list()
        assert shim.fake.finished == []  # the Kifli MCP was not asked
        return names

    # before the fix: an empty list, or (while the sign-in hung) no answer at all
    assert asyncio.run(go()) == ["get_cart"]


def test_before_the_first_sign_in_the_list_is_empty(tmp_path):
    assert asyncio.run(Shim(tmp_path, logged_in=False).list()) == []


def test_a_hanging_listing_is_answered_in_time_and_left_running(tmp_path, monkeypatch):
    _seen_once(tmp_path)
    monkeypatch.setattr(mcp_schema_shim, "LIST_TIMEOUT", 0.2)

    async def go():
        shim = Shim(tmp_path)
        shim.fake.mode = "hang"
        names = await asyncio.wait_for(shim.list(), 5)  # before the fix: waited as long as Kifli did
        # not cancelled: a new sign-in may be running in it
        assert len(shim.upstream._calls) == 1
        shim.fake.release.set()
        await asyncio.sleep(0.05)
        assert shim.fake.finished == ["list"]
        assert not shim.upstream._lost.is_set()
        return names

    assert asyncio.run(go()) == ["get_cart"]


def test_a_failed_listing_is_answered_from_the_saved_list_and_renews_the_session(tmp_path):
    _seen_once(tmp_path)

    async def go():
        shim = Shim(tmp_path)
        shim.fake.mode = "fail"
        names = await shim.list()  # before the fix: an error, so Home Assistant's setup failed
        assert shim.upstream._lost.is_set()
        return names

    assert asyncio.run(go()) == ["get_cart"]


# --- tool calls ----------------------------------------------------------------------------------

def test_a_call_works_when_kifli_is_reachable(tmp_path):
    result = asyncio.run(Shim(tmp_path).call())
    assert not result.isError
    assert _text(result) == "2 tétel"


def test_a_call_while_a_sign_in_is_needed_says_kifli_is_unavailable(tmp_path):
    _seen_once(tmp_path)
    result = asyncio.run(Shim(tmp_path, logged_in=False).call())
    assert result.isError
    assert "jelenleg nem érhető el" in _text(result)
    assert "be kell jelentkezni" in _text(result)


def test_a_call_while_reconnecting_says_kifli_is_unavailable(tmp_path):
    _seen_once(tmp_path)
    result = asyncio.run(Shim(tmp_path, session=False).call())
    assert result.isError
    assert "jelenleg nem érhető el" in _text(result)
    assert "próbáld újra" in _text(result)


def test_a_hanging_call_is_answered_in_time_and_left_running(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_schema_shim, "CALL_TIMEOUT", 0.2)

    async def go():
        shim = Shim(tmp_path)
        await shim.list()
        shim.fake.mode = "hang"
        result = await asyncio.wait_for(shim.call(), 5)
        # Kifli may still carry it out (e.g. add to the cart): it is not cancelled halfway
        shim.fake.release.set()
        await asyncio.sleep(0.05)
        assert shim.fake.finished == ["list", "call get_cart"]
        return result

    result = asyncio.run(go())
    assert result.isError
    assert "nem válaszolt" in _text(result)
    assert "kosarat" in _text(result)  # check before repeating it


def test_a_request_that_fails_after_its_caller_gave_up_still_renews_the_session(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_schema_shim, "CALL_TIMEOUT", 0.2)

    async def go():
        shim = Shim(tmp_path)
        await shim.list()
        shim.fake.mode = "hang"
        await shim.call()
        assert not shim.upstream._lost.is_set()
        shim.fake.mode = "fail"
        shim.fake.release.set()
        await asyncio.sleep(0.05)
        return shim.upstream._lost.is_set()

    assert asyncio.run(go())


# --- the saved list ------------------------------------------------------------------------------

@pytest.mark.parametrize("content", ["{not json", '{"tools": [{"name": 5}]}', "[]"])
def test_an_unreadable_saved_list_is_skipped(tmp_path, content):
    (tmp_path / "tools_cache.json").write_text(content, encoding="utf-8")
    assert ToolCache(tmp_path / "tools_cache.json").tools == []


def test_an_unchanged_list_is_not_written_again(tmp_path):
    _seen_once(tmp_path)
    path = tmp_path / "tools_cache.json"
    path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")  # same content, new mtime
    touched = path.stat().st_mtime_ns
    cache = ToolCache(path)
    cache.save([PING])
    assert path.stat().st_mtime_ns == touched


# --- the Home Assistant notification -------------------------------------------------------------

def test_the_notification_is_shown_when_a_sign_in_is_needed_and_dismissed_after(tmp_path, monkeypatch):
    sent: list[tuple[str, dict]] = []
    real_client = httpx.AsyncClient

    def supervisor(req: httpx.Request) -> httpx.Response:
        assert req.headers["authorization"] == "Bearer SUPERVISOR"
        sent.append((req.url.path, json.loads(req.content)))
        return httpx.Response(200, json=[])

    def client(**kw):
        kw.setdefault("transport", httpx.MockTransport(supervisor))
        return real_client(**kw)

    monkeypatch.setenv("SUPERVISOR_TOKEN", "SUPERVISOR")
    monkeypatch.setattr(kifli_auth.httpx, "AsyncClient", client)
    auth = AuthManager(MCP_URL, tmp_path)

    async def go():
        await auth._on_redirect("https://identity.kifli.hu/oauth2/authorize?state=S")
        await auth._on_redirect("https://identity.kifli.hu/oauth2/authorize?state=T")  # not twice
        auth.status = "exchanging"
        auth._sign_in_done(None)
        while auth._background:
            await asyncio.sleep(0.01)

    asyncio.run(go())
    assert [path for path, _ in sent] == ["/core/api/services/persistent_notification/create",
                                          "/core/api/services/persistent_notification/dismiss"]
    assert {p["notification_id"] for _, p in sent} == {kifli_auth.SIGN_IN_NOTIFICATION_ID}
    assert "Kifli MCP" in sent[0][1]["message"]


def test_a_failed_notification_does_not_break_the_sign_in(tmp_path, monkeypatch):
    real_client = httpx.AsyncClient

    def client(**kw):
        kw.setdefault("transport", httpx.MockTransport(lambda req: httpx.Response(502)))
        return real_client(**kw)

    monkeypatch.setenv("SUPERVISOR_TOKEN", "SUPERVISOR")
    monkeypatch.setattr(kifli_auth.httpx, "AsyncClient", client)
    asyncio.run(kifli_auth.notify_sign_in_needed(True))  # logged, not raised
