"""Eszközönkénti ki/be kapcsolás + új / megszűnt eszközök jelzése.

A Rohlik Group MCP eszközlistája a szerverről jön, és bármikor bővülhet. Itt
tartjuk nyilván, melyik eszközt ismerjük már, melyik engedélyezett, és ha az
upstream lista változik, jelzünk a Home Assistantnak (értesítés + esemény).

Tárolás: /data/tool_settings.json
  {
    "tools": {"<név>": {"enabled": true, "description": "...", "first_seen": "..."}},
    "removed": ["<név>", ...]
  }

Első induláskor (nincs fájl) minden akkor látott eszköz engedélyezett – így
frissítéskor semmi nem tűnik el. Ami ezután jelenik meg, az a
``new_tools_enabled`` opció szerint indul (alapból KIKAPCSOLVA), és értesítés
megy róla.

Minden napló a STDERR-re megy: a STDOUT az MCP stdio csatorna.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
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


class ToolSettings:
    def __init__(self, path: Path, new_tools_enabled: bool) -> None:
        self.path = path
        self.new_tools_enabled = new_tools_enabled
        # megjelenítési nyelv: a 'country' opció (hu → magyar leírások)
        self.lang = os.environ.get("KIFLI_LANG", "en")
        self.tools: dict[str, dict] = {}
        self.removed: list[str] = []
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
            self.rev = int(data.get("rev") or 0)
        except (ValueError, TypeError, AttributeError) as ex:
            self.tools, self.removed, self.rev = {}, [], 0
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
            json.dumps({"tools": self.tools, "removed": self.removed, "rev": self.rev}, ensure_ascii=False, indent=1),
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

    # --- módosítás -------------------------------------------------------------
    def sync(self, upstream: dict[str, str]) -> tuple[list[str], list[str]]:
        """Összeveti az upstream listát (név → leírás) a nyilvántartással.
        Visszaadja az új és a megszűnt eszközök nevét (első induláskor üres)."""
        first_run = not self.initialized
        new: list[str] = []
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
            else:
                entry["description"] = desc
                entry.pop("missing", None)
        self.removed = [n for n in self.removed if n not in upstream]
        removed: list[str] = []
        for name, entry in self.tools.items():
            if name not in upstream and not entry.get("missing"):
                entry["missing"] = True
                removed.append(name)
                if name not in self.removed:
                    self.removed.append(name)
        changed = first_run or new or removed
        self.initialized = True
        if changed:
            self._save()
        return new, removed

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

async def notify_ha(new: list[str], removed: list[str], settings: ToolSettings) -> None:
    """Állandó értesítés + esemény a HA-ban. Az esemény automatizálásból
    továbbítható (Telegram, mobil értesítés stb.)."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        log.info("Nincs SUPERVISOR_TOKEN – az eszközváltozásról nem tudok értesítést küldeni.")
        return
    base = "http://supervisor/core/api"
    h = {"Authorization": f"Bearer {token}"}
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
    calls: list[tuple[str, dict, str]] = [(
        "services/persistent_notification/create",
        {"title": "Kifli MCP – változott a funkciólista",
         "message": "\n".join(lines), "notification_id": NOTIFICATION_ID},
        "értesítés",
    )]
    calls += [(f"events/{EVENT_NEW}", {
        "tool": n,
        "description": _short(settings.display_description(n), 500),
        "enabled": settings.is_enabled(n),
    }, f"{EVENT_NEW} {n}") for n in new]
    calls += [(f"events/{EVENT_REMOVED}", {"tool": n}, f"{EVENT_REMOVED} {n}") for n in removed]
    failed: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            # egy hibás hívás ne vigye el a többit; a HTTP-hibát is hibának vesszük
            for path, payload, what in calls:
                try:
                    r = await c.post(f"{base}/{path}", headers=h, json=payload)
                    r.raise_for_status()
                except httpx.HTTPError as ex:
                    failed.append(f"{what} ({ex})")
    except Exception as ex:  # noqa: BLE001 – kényelmi funkció, ne döntse be a shimet
        failed.append(f"kapcsolat ({ex})")
    if failed:
        log.warning("Eszközváltozás jelzése a HA-nak nem (teljesen) sikerült: %s", "; ".join(failed))
    else:
        log.info("Eszközváltozás jelezve a HA-nak: új=%s, megszűnt=%s", new, removed)
