"""Eszközönkénti ki/be kapcsolás + új / megszűnt eszközök jelzése.

A Rohlik Group MCP eszközlistája a szerverről jön, és bármikor bővülhet. Itt
tartjuk nyilván, melyik eszközt ismerjük már, melyik engedélyezett, és ha az
upstream lista változik, jelzünk a Home Assistantnak (értesítés + esemény).

Tárolás: /data/tool_settings.json
  {
    "tools": {"<név>": {"enabled": true, "description": "...", "first_seen": "..."}},
    "removed": ["<név>", ...],
    "pending": {"notification": {"new": [...], "removed": [...]},
                "event": {"new": [...], "removed": [...]}}
  }

Első induláskor (nincs fájl) minden akkor látott eszköz engedélyezett – így
frissítéskor semmi nem tűnik el. Ami ezután jelenik meg, az a
``new_tools_enabled`` opció szerint indul (alapból KIKAPCSOLVA), és értesítés
megy róla.

Delivery is at-least-once: a change stays in "pending" until Home Assistant has
accepted it, separately for the notification and for the automation events, and
is retried at the next tool listing.

Minden napló a STDERR-re megy: a STDOUT az MCP stdio csatorna.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
from tool_descriptions_hu import describe

log = logging.getLogger("kifli.tools")

EVENT_NEW = "kifli_mcp_new_tool"
EVENT_REMOVED = "kifli_mcp_removed_tool"
NOTIFICATION_ID = "kifli_mcp_tools_changed"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _short(desc: str, limit: int = 160) -> str:
    desc = " ".join((desc or "").split())
    return desc if len(desc) <= limit else desc[: limit - 1] + "…"


# the two ways a change is reported, tracked separately so that a retry resends only what failed
CHANNELS = ("notification", "event")


def _empty_pending() -> dict[str, dict[str, list[str]]]:
    return {ch: {"new": [], "removed": []} for ch in CHANNELS}


class ToolSettings:
    def __init__(self, path: Path, new_tools_enabled: bool) -> None:
        self.path = path
        self.new_tools_enabled = new_tools_enabled
        # megjelenítési nyelv: a 'country' opció (hu → magyar leírások)
        self.lang = os.environ.get("KIFLI_LANG", "en")
        self.tools: dict[str, dict] = {}
        self.removed: list[str] = []
        self.pending = _empty_pending()  # changes Home Assistant has not accepted yet
        self.notifying = False  # a delivery is in progress (only one at a time)
        self.rev = 0  # minden mentéskor nő – az elavult oldalról jövő mentést így ismerjük fel
        self.initialized = False
        self._load()

    # --- tárolás ---------------------------------------------------------------
    def _load(self) -> None:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return  # valódi első indulás: a sync mindent bekapcsol
        except OSError as ex:
            self._load_failed(f"nem olvasható ({ex})")
            return
        try:
            data = json.loads(raw)
            self.tools = {k: v for k, v in (data.get("tools") or {}).items() if isinstance(v, dict)}
            self.removed = [str(x) for x in data.get("removed") or []]
            pending = data.get("pending") or {}
            self.pending = {ch: {kind: [str(x) for x in (pending.get(ch) or {}).get(kind) or []]
                                 for kind in ("new", "removed")} for ch in CHANNELS}
            self.rev = int(data.get("rev") or 0)
        except (ValueError, TypeError, AttributeError) as ex:
            self.tools, self.removed, self.pending, self.rev = {}, [], _empty_pending(), 0
            self._load_failed(f"hibás tartalmú ({ex})")
            return
        self.initialized = True

    def _load_failed(self, reason: str) -> None:
        """Létező, de olvashatatlan beállításfájl – ez NEM első indulás, tehát nem
        kapcsolunk be mindent (a felhasználó kikapcsolt eszközei is bekapcsolnának).
        Biztonságos irányba bukunk: minden eszköz újként, a ``new_tools_enabled``
        szerint (alapból kikapcsolva) érkezik, és értesítés megy róla. A hibás
        fájlt félretesszük, hogy ne íródjon felül nyom nélkül."""
        log.error("A %s %s – az eszközök a 'new_tools_enabled' szerint indulnak, a fájl .corrupt néven félretéve.",
                  self.path, reason)
        with contextlib.suppress(OSError):
            self.path.replace(self.path.with_suffix(".corrupt"))
        self.initialized = True

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.rev += 1
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"tools": self.tools, "removed": self.removed, "pending": self.pending, "rev": self.rev},
                       ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        with contextlib.suppress(OSError):
            tmp.chmod(0o600)
        tmp.replace(self.path)

    # --- lekérdezés ------------------------------------------------------------
    def is_enabled(self, name: str) -> bool:
        entry = self.tools.get(name)
        if entry is None:
            # még nem látott eszköz (pl. hívás a lista előtt): az opció dönt
            return self.new_tools_enabled
        return bool(entry.get("enabled"))

    def display_description(self, name: str) -> str:
        return describe(name, str(self.tools.get(name, {}).get("description", "")), self.lang)

    def listing(self) -> list[tuple[str, dict]]:
        """Rendezett lista a felülethez, a leírás a megjelenítési nyelven."""
        return [(n, {**e, "description": self.display_description(n)}) for n, e in sorted(self.tools.items())]

    def has_pending(self) -> bool:
        return any(names for queues in self.pending.values() for names in queues.values())

    # --- módosítás -------------------------------------------------------------
    def sync(self, upstream: dict[str, str]) -> tuple[list[str], list[str]]:
        """Összeveti az upstream listát (név → leírás) a nyilvántartással.
        Visszaadja az új és a megszűnt eszközök nevét (első induláskor üres),
        és felveszi őket a még kézbesítendő változások közé."""
        first_run = not self.initialized
        new: list[str] = []
        returned: list[str] = []
        for name, desc in upstream.items():
            entry = self.tools.get(name)
            if entry is None:
                self.tools[name] = {
                    "enabled": True if first_run else self.new_tools_enabled,
                    "description": desc,
                    "first_seen": _now(),
                }
                if not first_run:
                    self.tools[name]["is_new"] = True  # mentésig "új" címkét kap az oldalon
                    new.append(name)
                    self._pend_new(name)
            else:
                entry["description"] = desc
                if entry.pop("missing", None):
                    returned.append(name)
                    self._unpend_removed(name)
        self.removed = [n for n in self.removed if n not in upstream]
        removed: list[str] = []
        for name, entry in self.tools.items():
            if name not in upstream and not entry.get("missing"):
                entry["missing"] = True
                removed.append(name)
                self._pend_removed(name)
                if name not in self.removed:
                    self.removed.append(name)
        changed = first_run or new or removed or returned
        self.initialized = True
        if changed:
            self._save()
        return new, removed

    def _pend_new(self, name: str) -> None:
        for queues in self.pending.values():
            if name not in queues["new"]:
                queues["new"].append(name)

    def _pend_removed(self, name: str) -> None:
        for queues in self.pending.values():
            if name in queues["new"]:
                queues["new"].remove(name)  # appeared and vanished before it was reported: nothing to say
            elif name not in queues["removed"]:
                queues["removed"].append(name)

    def _unpend_removed(self, name: str) -> None:
        for queues in self.pending.values():
            if name in queues["removed"]:
                queues["removed"].remove(name)  # came back before its removal was reported

    def ack(self, channel: str, new: list[str], removed: list[str]) -> None:
        """Home Assistant accepted these changes on this channel: no retry for them."""
        queues = self.pending[channel]
        queues["new"] = [n for n in queues["new"] if n not in new]
        queues["removed"] = [n for n in queues["removed"] if n not in removed]
        if new or removed:
            self._save()

    def set_enabled(self, enabled_names: set[str]) -> None:
        for name, entry in self.tools.items():
            if entry.get("missing"):
                # a lapon le van tiltva, a böngésző nem küldi – ne kapcsoljuk ki emiatt,
                # hogy ha visszajön, a korábbi állapotában jöjjön vissza
                continue
            entry["enabled"] = name in enabled_names
            entry.pop("is_new", None)
        self._save()


# --- Home Assistant értesítés ---------------------------------------------------

def _notification_message(new: list[str], removed: list[str], settings: ToolSettings) -> str:
    lines: list[str] = []
    if new:
        state = "bekapcsolva" if settings.new_tools_enabled else "KIKAPCSOLVA"
        lines.append(f"**Új Kifli-funkció ({state}):**")
        for n in new:
            lines.append(f"- `{n}` – {_short(settings.display_description(n))}")
    if removed:
        lines.append("**Megszűnt Kifli-funkció:**")
        lines.extend(f"- `{n}`" for n in removed)
    lines.append("")
    lines.append("Ki/bekapcsolás: oldalsáv → **Kifli MCP** → Funkciók.")
    return "\n".join(lines)


async def notify_ha(settings: ToolSettings) -> None:
    """Állandó értesítés + esemény a HA-ban. Az esemény automatizálásból
    továbbítható (Telegram, mobil értesítés stb.).

    Sends what is still pending. Whatever Home Assistant does not accept stays
    pending and is retried at the next tool listing; the notification and the
    events are acknowledged separately, so a retry resends only what failed."""
    if settings.notifying or not settings.has_pending():
        return
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        log.info("Nincs SUPERVISOR_TOKEN – az eszközváltozásról nem tudok értesítést küldeni.")
        return
    base = "http://supervisor/core/api"
    h = {"Authorization": f"Bearer {token}"}
    failed: list[str] = []
    settings.notifying = True
    try:
        async with httpx.AsyncClient(timeout=20) as c:

            async def post(path: str, payload: dict, what: str) -> bool:
                # one failed call must not stop the others; an HTTP error status counts as a failure
                try:
                    r = await c.post(f"{base}/{path}", headers=h, json=payload)
                    r.raise_for_status()
                except httpx.HTTPError as ex:
                    failed.append(f"{what} ({ex})")
                    return False
                return True

            note = settings.pending["notification"]
            new, removed = list(note["new"]), list(note["removed"])
            if (new or removed) and await post(
                "services/persistent_notification/create",
                # a separate notification per report, so an unread earlier one is not overwritten
                {"title": "Kifli MCP – változott a funkciólista",
                 "message": _notification_message(new, removed, settings),
                 "notification_id": f"{NOTIFICATION_ID}_{uuid.uuid4().hex[:8]}"},
                "értesítés",
            ):
                settings.ack("notification", new, removed)

            events = settings.pending["event"]
            sent_new = [n for n in list(events["new"]) if await post(f"events/{EVENT_NEW}", {
                "tool": n,
                "description": _short(settings.display_description(n), 500),
                "enabled": settings.is_enabled(n),
            }, f"{EVENT_NEW} {n}")]
            sent_removed = [n for n in list(events["removed"])
                            if await post(f"events/{EVENT_REMOVED}", {"tool": n}, f"{EVENT_REMOVED} {n}")]
            settings.ack("event", sent_new, sent_removed)
    except Exception as ex:  # noqa: BLE001 – kényelmi funkció, ne döntse be a shimet
        failed.append(f"kapcsolat ({ex})")
    finally:
        settings.notifying = False
    if failed:
        log.warning("Eszközváltozás jelzése a HA-nak nem (teljesen) sikerült, a következő listázáskor újra: %s",
                    "; ".join(failed))
    else:
        log.info("Eszközváltozás jelezve a HA-nak.")
