"""Per-tool on/off switches and tool-list change notifications (#3).

Of the CodeRabbit findings on #3, this file catches: a corrupt settings file
enabling every tool, a temporarily missing tool being disabled on save, and
HTTP errors in the notification being logged as success.
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


# --- first start, update -------------------------------------------------------------------------

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


# --- new and removed tools -----------------------------------------------------------------------

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
    # a call before the first listing (e.g. after a restart): the option decides
    assert ToolSettings(path, new_tools_enabled=False).is_enabled("never_seen") is False
    assert ToolSettings(path, new_tools_enabled=True).is_enabled("never_seen") is True


def test_saving_keeps_the_selection_of_a_temporarily_missing_tool(path):
    settings = ToolSettings(path, new_tools_enabled=False)
    settings.sync(UPSTREAM)
    settings.sync({k: v for k, v in UPSTREAM.items() if k != "get_cart"})
    # on the page the missing tool's checkbox is disabled, so the browser does not submit it
    submitted = {n for n, e in settings.listing() if e.get("enabled") and not e.get("missing")}
    settings.set_enabled(submitted)
    settings.sync(UPSTREAM)
    assert settings.is_enabled("get_cart") is True


# --- corrupt settings file: fail closed ----------------------------------------------------------

@pytest.mark.parametrize("content", ["{not json", "[]", '{"tools": {}, "rev": "x"}', '{"tools": ["x"]}'])
def test_corrupt_file_fails_closed(path, content):
    path.write_text(content, encoding="utf-8")
    settings = ToolSettings(path, new_tools_enabled=False)
    new, removed = settings.sync(UPSTREAM)
    assert not any(_enabled(settings).values())  # NOT everything on, unlike a first start
    assert sorted(new) == sorted(UPSTREAM)  # and a notification goes out
    assert removed == []
    assert path.with_suffix(".corrupt").read_text(encoding="utf-8") == content  # the broken file is kept
    json.loads(path.read_text(encoding="utf-8"))  # the new file is valid again


# --- display -------------------------------------------------------------------------------------

def test_hungarian_descriptions_only_for_hu(path, monkeypatch):
    monkeypatch.setenv("KIFLI_LANG", "hu")
    hu = ToolSettings(path, new_tools_enabled=False)
    hu.sync(UPSTREAM)
    assert dict(hu.listing())["get_cart"]["description"] != "Cart"

    monkeypatch.setenv("KIFLI_LANG", "cz")
    cz = ToolSettings(path, new_tools_enabled=False)
    assert dict(cz.listing())["get_cart"]["description"] == "Cart"


# --- Home Assistant notification -----------------------------------------------------------------

def _mock_ha(monkeypatch, status_for):
    """Point tool_settings' httpx client at a fake Supervisor API; returns the request paths."""
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
    assert len(seen) == 2  # the event was still sent after the notification failed
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    assert not any("jelezve" in r.getMessage() for r in caplog.records)  # no false "notified" log


def test_notify_without_supervisor_token_does_nothing(path, monkeypatch):
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    seen = _mock_ha(monkeypatch, lambda _p: 200)
    settings = ToolSettings(path, new_tools_enabled=False)
    asyncio.run(notify_ha(["x"], [], settings))
    assert seen == []
