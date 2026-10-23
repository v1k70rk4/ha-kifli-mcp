"""Per-tool on/off switches and tool-list change notifications (#3).

Of the CodeRabbit findings on #3, this file catches: a corrupt settings file
enabling every tool, a temporarily missing tool being disabled on save, HTTP
errors in the notification being logged as success, and a failed notification
being lost instead of retried.
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
# captured once: a test may patch the client several times, each patch must wrap the real one
REAL_ASYNC_CLIENT = httpx.AsyncClient


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

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(status_for(request.url.path))

    monkeypatch.setattr(tool_settings.httpx, "AsyncClient",
                        lambda **kw: REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler), **kw))
    return seen


NOTIFICATION = "/core/api/services/persistent_notification/create"
EVENT_NEW = f"/core/api/events/{tool_settings.EVENT_NEW}"
EVENT_REMOVED = f"/core/api/events/{tool_settings.EVENT_REMOVED}"


@pytest.fixture
def changed(path):
    """Settings where one tool appeared and one disappeared since the first start."""
    settings = ToolSettings(path, new_tools_enabled=False)
    settings.sync(UPSTREAM)
    grown = {**UPSTREAM, "reserve_timeslot": "Book a slot"}
    del grown["cancel_order"]
    assert settings.sync(grown) == (["reserve_timeslot"], ["cancel_order"])
    return settings


def test_notify_sends_notification_and_events(changed, monkeypatch, caplog):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "t")
    seen = _mock_ha(monkeypatch, lambda _p: 200)
    with caplog.at_level(logging.INFO, logger="kifli.tools"):
        asyncio.run(notify_ha(changed))
    assert seen == [NOTIFICATION, EVENT_NEW, EVENT_REMOVED]
    assert not changed.has_pending()
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    asyncio.run(notify_ha(changed))
    assert len(seen) == 3  # delivered once, nothing to resend


def test_notify_reports_http_errors_and_keeps_going(changed, monkeypatch, caplog):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "t")
    seen = _mock_ha(monkeypatch, lambda p: 500 if "persistent_notification" in p else 200)
    with caplog.at_level(logging.INFO, logger="kifli.tools"):
        asyncio.run(notify_ha(changed))
    assert seen == [NOTIFICATION, EVENT_NEW, EVENT_REMOVED]  # the events still went out
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    assert not any("jelezve" in r.getMessage() for r in caplog.records)  # no false "notified" log


# --- retry: a failed delivery is not lost (CodeRabbit on #3) -------------------------------------

def test_failed_notification_is_retried_without_resending_the_events(changed, path, monkeypatch):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "t")
    _mock_ha(monkeypatch, lambda p: 500 if "persistent_notification" in p else 200)
    asyncio.run(notify_ha(changed))
    assert changed.has_pending()

    # survives a restart, and the next tool listing retries only what failed
    after_restart = ToolSettings(path, new_tools_enabled=False)
    assert after_restart.pending["notification"] == {"new": ["reserve_timeslot"], "removed": ["cancel_order"]}
    assert after_restart.pending["event"] == {"new": [], "removed": []}
    seen = _mock_ha(monkeypatch, lambda _p: 200)
    asyncio.run(notify_ha(after_restart))
    assert seen == [NOTIFICATION]
    assert not after_restart.has_pending()


def test_failed_event_is_retried_without_resending_the_notification(changed, monkeypatch):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "t")
    _mock_ha(monkeypatch, lambda p: 500 if p == EVENT_NEW else 200)
    asyncio.run(notify_ha(changed))
    assert changed.pending["event"] == {"new": ["reserve_timeslot"], "removed": []}

    seen = _mock_ha(monkeypatch, lambda _p: 200)
    asyncio.run(notify_ha(changed))
    assert seen == [EVENT_NEW]
    assert not changed.has_pending()


def test_unreachable_home_assistant_keeps_everything_pending(changed, monkeypatch):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "t")

    def handler(request):
        raise httpx.ConnectError("supervisor down", request=request)

    monkeypatch.setattr(tool_settings.httpx, "AsyncClient",
                        lambda **kw: REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler), **kw))
    asyncio.run(notify_ha(changed))
    for channel in tool_settings.CHANNELS:
        assert changed.pending[channel] == {"new": ["reserve_timeslot"], "removed": ["cancel_order"]}


def test_notify_without_supervisor_token_keeps_it_pending(changed, monkeypatch):
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    seen = _mock_ha(monkeypatch, lambda _p: 200)
    asyncio.run(notify_ha(changed))
    assert seen == []
    assert changed.has_pending()


def test_concurrent_listings_deliver_once(changed, monkeypatch):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "t")
    seen = _mock_ha(monkeypatch, lambda _p: 200)

    async def two_listings_at_once():
        await asyncio.gather(notify_ha(changed), notify_ha(changed))

    asyncio.run(two_listings_at_once())
    assert seen == [NOTIFICATION, EVENT_NEW, EVENT_REMOVED]


def test_each_report_is_a_separate_notification(changed, monkeypatch):
    # with a fixed notification_id a later report would overwrite an earlier, unread one
    monkeypatch.setenv("SUPERVISOR_TOKEN", "t")
    ids: list[str] = []

    def handler(request):
        if request.url.path == NOTIFICATION:
            ids.append(json.loads(request.content)["notification_id"])
        return httpx.Response(200)

    monkeypatch.setattr(tool_settings.httpx, "AsyncClient",
                        lambda **kw: REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler), **kw))
    asyncio.run(notify_ha(changed))
    changed.sync({**UPSTREAM, "reserve_timeslot": "Book a slot", "submit_claim": "Claim"})
    asyncio.run(notify_ha(changed))
    assert len(ids) == 2
    assert len(set(ids)) == 2


def test_change_that_reverts_before_delivery_is_not_reported(path):
    settings = ToolSettings(path, new_tools_enabled=False)
    settings.sync(UPSTREAM)
    settings.sync({**UPSTREAM, "flash_tool": "x"})  # appears…
    settings.sync(UPSTREAM)  # …and is gone again before anything was delivered
    settings.sync({k: v for k, v in UPSTREAM.items() if k != "get_cart"})  # disappears…
    settings.sync(UPSTREAM)  # …and is back
    assert not settings.has_pending()


def test_returning_tool_is_saved(path):
    settings = ToolSettings(path, new_tools_enabled=False)
    settings.sync(UPSTREAM)
    settings.sync({k: v for k, v in UPSTREAM.items() if k != "get_cart"})
    settings.sync(UPSTREAM)
    assert "missing" not in dict(ToolSettings(path, new_tools_enabled=False).listing())["get_cart"]
