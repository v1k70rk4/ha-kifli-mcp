"""The Tools card on the Kifli MCP page (#3), as the browser uses it.

Of the CodeRabbit findings on #3, this file catches that a save reported the
HA MCP integration reload as successful even when it failed, and – end to end
through the page – that a temporarily missing tool got disabled on save.
"""

from __future__ import annotations

import asyncio
import re

import httpx
import pytest
from kifli_auth import AuthManager, build_app
from tool_settings import ToolSettings

UPSTREAM = {"batch_search_products": "Search", "get_cart": "Cart", "cancel_order": "Cancel"}


async def _login_ok() -> str:
    return ""


class Reload:
    """Fake on_tools_saved: the result of reloading the HA MCP integration."""

    def __init__(self, ok: bool) -> None:
        self.ok = ok
        self.calls = 0

    async def __call__(self) -> tuple[bool, str]:
        self.calls += 1
        return self.ok, "MCP :42783 → " + ("200" if self.ok else "500")


@pytest.fixture
def settings(tmp_path):
    s = ToolSettings(tmp_path / "tool_settings.json", new_tools_enabled=False)
    s.sync(UPSTREAM)
    return s


def _call(settings, reload, method, path, **kw) -> httpx.Response:
    app = build_app(AuthManager("https://mcp.kifli.hu/mcp", settings.path.parent), 42783, _login_ok, settings, reload)

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ingress") as c:
            return await c.request(method, path, **kw)

    return asyncio.run(go())


def _save(settings, reload, tools, rev=None):
    return _call(settings, reload, "POST", "/tools",
                 data={"rev": str(settings.rev if rev is None else rev), "tool": sorted(tools)})


def _toast(resp: httpx.Response) -> tuple[str, str]:
    m = re.search(r'<div class="toast ([a-z]+)">([^<]*)</div>', resp.text)
    assert m, "no feedback (toast) on the page"
    return m.group(1), m.group(2)


# --- saving and reloading the HA MCP integration -------------------------------------------------

def test_save_with_successful_reload(settings):
    reload = Reload(ok=True)
    resp = _save(settings, reload, {"batch_search_products", "get_cart"})
    cls, text = _toast(resp)
    assert (cls, reload.calls) == ("ok", 1)
    assert "újratöltve" in text
    assert settings.is_enabled("cancel_order") is False


def test_failed_reload_is_a_warning_not_a_success(settings):
    reload = Reload(ok=False)
    resp = _save(settings, reload, {"batch_search_products"})
    cls, text = _toast(resp)
    assert cls == "warn"
    assert "nem sikerült" in text
    assert "újratöltve" not in text
    # the save itself still happened
    assert settings.is_enabled("get_cart") is False


def test_stale_page_is_rejected_and_changes_nothing(settings):
    reload = Reload(ok=True)
    old_rev = settings.rev
    settings.set_enabled(set(UPSTREAM))  # meanwhile someone saved from another tab
    resp = _save(settings, reload, set(), rev=old_rev)
    cls, text = _toast(resp)
    assert cls == "err"
    assert "elavult" in text
    assert all(settings.is_enabled(n) for n in UPSTREAM)
    assert reload.calls == 0


def test_json_save_for_scripts(settings):
    reload = Reload(ok=True)
    resp = _call(settings, reload, "POST", "/tools", json={"enabled": ["get_cart"]})
    assert _toast(resp)[0] == "ok"
    assert [n for n in UPSTREAM if settings.is_enabled(n)] == ["get_cart"]


def test_json_save_with_wrong_shape_changes_nothing(settings):
    reload = Reload(ok=True)
    resp = _call(settings, reload, "POST", "/tools", json=["get_cart"])
    assert _toast(resp)[0] == "err"
    assert all(settings.is_enabled(n) for n in UPSTREAM)
    assert reload.calls == 0


# --- rendering -----------------------------------------------------------------------------------

def test_tools_card_lists_tools_and_escapes_upstream_text(settings):
    settings.sync({**UPSTREAM, "evil<b>tool</b>": '<img src=x onerror="alert(1)">'})
    page = _call(settings, Reload(ok=True), "GET", "/").text
    assert "Funkciók / Tools" in page
    assert f'name="rev" value="{settings.rev}"' in page
    assert "<b>tool</b>" not in page
    assert "<img src=x" not in page
    assert "evil&lt;b&gt;tool&lt;/b&gt;" in page


def test_missing_tool_keeps_its_selection_when_saved_from_the_page(settings):
    settings.sync({k: v for k, v in UPSTREAM.items() if k != "get_cart"})  # get_cart is gone for a while
    page = _call(settings, Reload(ok=True), "GET", "/").text
    checkbox = re.search(r'<input type="checkbox" name="tool" value="get_cart"[^>]*>', page).group(0)
    assert "disabled" in checkbox  # the browser does not submit a disabled field

    # what the browser actually submits: the checked fields that are not disabled
    submitted = set(re.findall(r'<input type="checkbox" name="tool" value="([^"]+)" checked>', page))
    assert "get_cart" not in submitted
    _save(settings, Reload(ok=True), submitted)

    settings.sync(UPSTREAM)  # it comes back
    assert settings.is_enabled("get_cart") is True
