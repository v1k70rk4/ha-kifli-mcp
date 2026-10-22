"""Eszközönkénti ki/be kapcsolás és az eszközlista változásának jelzése (#3).

A CodeRabbit #3-as megállapításai közül ez a fájl fogja meg: a sérült
beállításfájlnál mindent bekapcsoló hibát, az átmenetileg eltűnt eszköz
kikapcsolódását mentéskor, és a HTTP-hibát sikerként naplózó értesítést.
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest
import tool_settings
from tool_settings import ToolSettings, notify_ha

UPSTREAM = {"batch_search_products": "Search", "get_cart": "Cart", "cancel_order": "Cancel"}


@pytest.fixture
def path(tmp_path):
    return tmp_path / "tool_settings.json"


def _enabled(settings, names=UPSTREAM):
    return {n: settings.is_enabled(n) for n in names}


# --- első indulás, frissítés --------------------------------------------------------------------

def test_first_start_enables_everything_and_reports_nothing(path):
    settings = ToolSettings(path, new_tools_enabled=False)
    assert settings.sync(UPSTREAM) == ([], [])
    assert all(_enabled(settings).values())
    assert path.exists()


def test_selection_and_revision_survive_a_restart(path):
    settings = ToolSettings(path, new_tools_enabled=False)
    settings.sync(UPSTREAM)
    settings.set_enabled({"batch_search_products", "get_cart"})
    rev = settings.rev

    again = ToolSettings(path, new_tools_enabled=False)
    assert again.sync(UPSTREAM) == ([], [])
    assert _enabled(again) == {"batch_search_products": True, "get_cart": True, "cancel_order": False}
    assert again.rev == rev


# --- új és megszűnt eszközök --------------------------------------------------------------------

@pytest.mark.parametrize("new_tools_enabled", [False, True])
def test_new_tool_follows_the_option_and_is_reported_once(path, new_tools_enabled):
    settings = ToolSettings(path, new_tools_enabled=new_tools_enabled)
    settings.sync(UPSTREAM)
    grown = {**UPSTREAM, "reserve_timeslot": "Book a slot"}
    assert settings.sync(grown) == (["reserve_timeslot"], [])
    assert settings.is_enabled("reserve_timeslot") is new_tools_enabled
    assert settings.sync(grown) == ([], [])


def test_removed_tool_is_reported_once_and_marked_missing(path):
    settings = ToolSettings(path, new_tools_enabled=False)
    settings.sync(UPSTREAM)
    shrunk = {k: v for k, v in UPSTREAM.items() if k != "get_cart"}
    assert settings.sync(shrunk) == ([], ["get_cart"])
    assert settings.sync(shrunk) == ([], [])
    assert dict(settings.listing())["get_cart"]["missing"] is True


def test_unknown_tool_follows_the_option(path):
    # hívás a lista előtt (pl. újraindítás után): az opció dönt
    assert ToolSettings(path, new_tools_enabled=False).is_enabled("never_seen") is False
    assert ToolSettings(path, new_tools_enabled=True).is_enabled("never_seen") is True


def test_saving_keeps_the_selection_of_a_temporarily_missing_tool(path):
    settings = ToolSettings(path, new_tools_enabled=False)
    settings.sync(UPSTREAM)
    settings.sync({k: v for k, v in UPSTREAM.items() if k != "get_cart"})
    # a lapon a megszűnt eszköz jelölőnégyzete le van tiltva, a böngésző nem küldi el
    submitted = {n for n, e in settings.listing() if e.get("enabled") and not e.get("missing")}
    settings.set_enabled(submitted)
    settings.sync(UPSTREAM)
    assert settings.is_enabled("get_cart") is True


# --- sérült beállításfájl: biztonságos irányba bukik ---------------------------------------------

@pytest.mark.parametrize("content", ["{nem json", "[]", '{"tools": {}, "rev": "x"}', '{"tools": ["x"]}'])
def test_corrupt_file_fails_closed(path, content):
    path.write_text(content, encoding="utf-8")
    settings = ToolSettings(path, new_tools_enabled=False)
    new, removed = settings.sync(UPSTREAM)
    assert not any(_enabled(settings).values())  # NEM kapcsol be mindent, mint első induláskor
    assert sorted(new) == sorted(UPSTREAM)  # értesítés megy róla
    assert removed == []
    assert path.with_suffix(".corrupt").read_text(encoding="utf-8") == content  # a hibás fájl megmarad
    json.loads(path.read_text(encoding="utf-8"))  # az új fájl már érvényes


# --- megjelenítés -------------------------------------------------------------------------------

def test_hungarian_descriptions_only_for_hu(path, monkeypatch):
    monkeypatch.setenv("KIFLI_LANG", "hu")
    hu = ToolSettings(path, new_tools_enabled=False)
    hu.sync(UPSTREAM)
    assert dict(hu.listing())["get_cart"]["description"] != "Cart"

    monkeypatch.setenv("KIFLI_LANG", "cz")
    cz = ToolSettings(path, new_tools_enabled=False)
    assert dict(cz.listing())["get_cart"]["description"] == "Cart"


# --- értesítés a Home Assistantnak --------------------------------------------------------------

def _mock_ha(monkeypatch, status_for):
    """A tool_settings httpx kliensét egy hamis Supervisor API-ra irányítja; visszaadja a kérések útvonalát."""
    seen: list[str] = []
    real = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(status_for(request.url.path))

    monkeypatch.setattr(tool_settings.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return seen


def test_notify_sends_notification_and_events(path, monkeypatch, caplog):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "t")
    seen = _mock_ha(monkeypatch, lambda _p: 200)
    settings = ToolSettings(path, new_tools_enabled=False)
    settings.sync(UPSTREAM)
    with caplog.at_level(logging.INFO, logger="kifli.tools"):
        asyncio.run(notify_ha(["reserve_timeslot"], ["cancel_order"], settings))
    assert seen == [
        "/core/api/services/persistent_notification/create",
        f"/core/api/events/{tool_settings.EVENT_NEW}",
        f"/core/api/events/{tool_settings.EVENT_REMOVED}",
    ]
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_notify_reports_http_errors_and_keeps_going(path, monkeypatch, caplog):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "t")
    seen = _mock_ha(monkeypatch, lambda p: 500 if "persistent_notification" in p else 200)
    settings = ToolSettings(path, new_tools_enabled=False)
    settings.sync(UPSTREAM)
    with caplog.at_level(logging.INFO, logger="kifli.tools"):
        asyncio.run(notify_ha(["reserve_timeslot"], [], settings))
    assert len(seen) == 2  # az értesítés hibája után az esemény is elment
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    assert not any("jelezve" in r.getMessage() for r in caplog.records)  # nincs hamis "siker"


def test_notify_without_supervisor_token_does_nothing(path, monkeypatch):
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    seen = _mock_ha(monkeypatch, lambda _p: 200)
    settings = ToolSettings(path, new_tools_enabled=False)
    asyncio.run(notify_ha(["x"], [], settings))
    assert seen == []
