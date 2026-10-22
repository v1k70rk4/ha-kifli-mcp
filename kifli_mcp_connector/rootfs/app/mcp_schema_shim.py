from __future__ import annotations

import asyncio
import contextlib
import copy
import logging
import os
from pathlib import Path
from typing import Any

import anyio
import mcp.server.stdio
import uvicorn
from kifli_auth import AuthManager, build_app, reload_ha_mcp_entry, setup_logging
from mcp import types
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from tool_settings import ToolSettings, notify_ha

SERVER_NAME = "kifli-schema-shim"
SERVER_VERSION = "2.1.0"

# Tool kihagyó rész, a HA / OpenAI schema-konverzió el tud hasalni rajtuk. v1.1 már kezeli.
IGNORE_WORDS = {
    # "claim",
    # "warranty",
    # "reclamation",
    # "complaint",
    # "refund",
    # "return",
    # "compensation",
    # "damage",
    # "credit",
    # "spread",
    # "reusable",
    # "bags",
}

# OpenAI/HA kompat: ha egy tool-nak nincs bemeneti paramétere, ne legyen üres a properties,
# mert egyes láncokban (HA serializer / OpenAI validation) így 400-ra fut.
PLACEHOLDER_ARG = "__ha_noop"


def _strip_dollar_keys(node: Any) -> Any:
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for k, v in node.items():
            if k.startswith("$"):
                continue
            out[k] = _strip_dollar_keys(v)
        return out
    if isinstance(node, list):
        return [_strip_dollar_keys(x) for x in node]
    return node


def _strip_unsupported_keywords(node: Any) -> Any:
    """
    Home Assistant MCP schema-konverter kompatibilitás:
    - uniqueItems: nem támogatott, ezért töröljük
    (Ide jöhetnek még később további kulcsok, ha előkerülnek.)
    """
    if isinstance(node, dict):
        node = dict(node)
        node.pop("uniqueItems", None)
        for k, v in list(node.items()):
            node[k] = _strip_unsupported_keywords(v)
        return node
    if isinstance(node, list):
        return [_strip_unsupported_keywords(x) for x in node]
    return node


def _normalize_exclusive_bounds(node: Any) -> Any:
    """
    HA 2026.9 regresszió elleni védelem.

    A HA ekkor váltott `voluptuous_openapi`-ról `probatio`-ra, és annak a
    from_openapi()/to_openapi() köre a draft 2020-12-es SZÁM alakú
    exclusiveMinimum/Maximum-ot a draft-04-es BOOLEAN alakra írja át:

        {"exclusiveMinimum": 0}  ->  {"minimum": 0, "exclusiveMinimum": true}

    Ez 2020-12 szerint érvénytelen (számot vár), és az Anthropic API
    emiatt 400-zal elutasítja az EGÉSZ tool listát:
        tools.NN.custom.input_schema: JSON schema is invalid.

    Ezért itt eleve nem engedjük ki az exclusive* kulcsokat: egész típusnál
    pontos inkluzív határra írjuk át, egyébként a határt megtartva elhagyjuk.
    """
    if isinstance(node, dict):
        node = {k: _normalize_exclusive_bounds(v) for k, v in node.items()}
        is_int = node.get("type") == "integer"

        ex_min = node.pop("exclusiveMinimum", None)
        if isinstance(ex_min, bool):
            pass  # draft-04 maradvány: csak dobjuk, a "minimum" marad
        elif isinstance(ex_min, (int, float)):
            bound = int(ex_min) + 1 if is_int else ex_min
            node["minimum"] = max(bound, node["minimum"]) if "minimum" in node else bound

        ex_max = node.pop("exclusiveMaximum", None)
        if isinstance(ex_max, bool):
            pass
        elif isinstance(ex_max, (int, float)):
            bound = int(ex_max) - 1 if is_int else ex_max
            node["maximum"] = min(bound, node["maximum"]) if "maximum" in node else bound

        return node

    if isinstance(node, list):
        return [_normalize_exclusive_bounds(x) for x in node]

    return node


def _inline_local_refs(schema: dict[str, Any]) -> dict[str, Any]:
    defs = schema.get("$defs") or schema.get("definitions") or {}

    def resolve_ref(ref: str) -> Any | None:
        if ref.startswith("#/$defs/"):
            return defs.get(ref[len("#/$defs/") :])
        if ref.startswith("#/definitions/"):
            return defs.get(ref[len("#/definitions/") :])
        return None

    seen: set[str] = set()

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                target = resolve_ref(ref)
                if target is not None:
                    if ref in seen:
                        return node
                    seen.add(ref)
                    merged = copy.deepcopy(target)
                    for k, v in node.items():
                        if k == "$ref":
                            continue
                        merged[k] = v
                    return walk(merged)

            out: dict[str, Any] = {}
            for k, v in node.items():
                if k in ("$defs", "definitions"):
                    continue
                out[k] = walk(v)
            return out

        if isinstance(node, list):
            return [walk(x) for x in node]

        return node

    return walk(schema)


def _pick_non_null_variant(variants: list[Any]) -> Any:
    dict_variants = [v for v in variants if isinstance(v, dict)]
    non_null = [v for v in dict_variants if v.get("type") != "null"]
    if non_null:
        return copy.deepcopy(non_null[0])
    if dict_variants:
        return copy.deepcopy(dict_variants[0])
    return {"type": "string"}


def _normalize_unions(node: Any) -> Any:
    if isinstance(node, dict):
        if "anyOf" in node and isinstance(node["anyOf"], list):
            chosen = _pick_non_null_variant(node["anyOf"])
            for k in ("description", "title", "enum", "examples"):
                if k in node and k not in chosen:
                    chosen[k] = node[k]
            if chosen.get("default") is None and chosen.get("type") not in ("null", None):
                chosen.pop("default", None)
            return _normalize_unions(chosen)

        if "oneOf" in node and isinstance(node["oneOf"], list):
            chosen = _pick_non_null_variant(node["oneOf"])
            for k in ("description", "title", "enum", "examples"):
                if k in node and k not in chosen:
                    chosen[k] = node[k]
            if chosen.get("default") is None and chosen.get("type") not in ("null", None):
                chosen.pop("default", None)
            return _normalize_unions(chosen)

        if "allOf" in node and isinstance(node["allOf"], list) and node["allOf"]:
            chosen = node["allOf"][0]
            if isinstance(chosen, dict):
                chosen = copy.deepcopy(chosen)
                for k in ("description", "title"):
                    if k in node and k not in chosen:
                        chosen[k] = node[k]
            return _normalize_unions(chosen)

        out: dict[str, Any] = {}
        for k, v in node.items():
            out[k] = _normalize_unions(v)
        return out

    if isinstance(node, list):
        return [_normalize_unions(x) for x in node]

    return node


def _ensure_types_ctx(node: Any, *, in_properties_map: bool = False) -> Any:
    """
    Kritikus: a `properties` alatti dict NEM schema, hanem mapping.
    Ott tilos "type"-ot kitalálni a mappingre (pl. a "items" nevű property miatt).
    """
    if isinstance(node, dict):
        if in_properties_map:
            out_map: dict[str, Any] = {}
            for k, v in node.items():
                if isinstance(v, dict):
                    out_map[k] = _ensure_types_ctx(v, in_properties_map=False)
            return out_map

        # default=None eltakarítás nem-null típusnál
        if node.get("default") is None and node.get("type") not in ("null", None):
            node.pop("default", None)

        # ha hiányzik type, próbáljuk kitalálni (csak valódi schema-n)
        if "type" not in node:
            if "properties" in node or "required" in node:
                node["type"] = "object"
            elif "items" in node:
                node["type"] = "array"
            elif "enum" in node:
                node["type"] = "string"

        out: dict[str, Any] = {}
        for k, v in node.items():
            if k == "properties" and isinstance(v, dict):
                out[k] = _ensure_types_ctx(v, in_properties_map=True)
            elif k == "items":
                out[k] = _ensure_types_ctx(v, in_properties_map=False)
            else:
                out[k] = _ensure_types_ctx(v, in_properties_map=False)
        return out

    if isinstance(node, list):
        return [_ensure_types_ctx(x, in_properties_map=False) for x in node]

    return node


def _force_openai_object_schema(schema: Any) -> dict[str, Any]:
    """
    OpenAI function parameters elvárás:
    - dict legyen
    - type=object
    - legyen 'properties' (akár üresen is)
    """
    if not isinstance(schema, dict) or not schema:
        return {"type": "object", "properties": {}, "additionalProperties": True}

    if schema.get("type") != "object":
        return {"type": "object", "properties": {}, "additionalProperties": True}

    schema.setdefault("properties", {})
    if not isinstance(schema["properties"], dict):
        schema["properties"] = {}

    schema.setdefault("additionalProperties", True)
    return schema


def _ensure_openai_properties_nonempty(schema: dict[str, Any]) -> dict[str, Any]:
    """
    Egyes HA/OpenAI láncoknál az üres properties (= {}) "eltűnhet" vagy invalid lesz.
    Rakunk bele egy NOOP placeholder property-t, ha üres.
    """
    if schema.get("type") == "object":
        schema.setdefault("properties", {})
        if not isinstance(schema["properties"], dict):
            schema["properties"] = {}

        if len(schema["properties"]) == 0:
            schema["properties"][PLACEHOLDER_ARG] = {
                "type": "string",
                "description": "Internal placeholder. Leave empty.",
            }

        schema.setdefault("additionalProperties", True)

    return schema


def _schema_has_non_dict_properties(schema: dict[str, Any]) -> bool:
    props = schema.get("properties")
    if not isinstance(props, dict):
        return False
    for v in props.values():
        if not isinstance(v, dict):
            return True
    return False


def simplify_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
    base = copy.deepcopy(schema) if isinstance(schema, dict) else {}

    base = _inline_local_refs(base)
    base = _normalize_unions(base)
    base = _strip_dollar_keys(base)
    base = _strip_unsupported_keywords(base)
    base = _normalize_exclusive_bounds(base)
    base = _ensure_types_ctx(base)

    # root sanity
    if not isinstance(base, dict) or not base:
        base = {"type": "object", "properties": {}, "additionalProperties": True}

    if base.get("type") is None and "properties" in base:
        base["type"] = "object"

    # OpenAI + HA kompatibilitás: object-hoz legyen properties
    base = _force_openai_object_schema(base)

    # OpenAI strict: properties ne legyen üres mapping
    base = _ensure_openai_properties_nonempty(base)

    return base


class Upstream:
    """A Rohlik Group MCP felé nyitott, hitelesített kapcsolat.

    Csak bejelentkezés után csatlakozik; ha a kapcsolat elszáll, újrapróbálja.
    Amíg nincs kapcsolat, a shim üres tool-listát ad – így a HA MCP-integráció
    betölt (nem időtúllépés), és az Assist többi része zavartalanul működik.
    """

    def __init__(self, url: str, auth: AuthManager) -> None:
        self.url = url
        self.auth = auth
        self.session: ClientSession | None = None
        self.ready = asyncio.Event()
        self._lost = asyncio.Event()
        self.log = logging.getLogger("kifli.upstream")

    async def run(self) -> None:
        backoff = 5
        while True:
            await self.auth.logged_in.wait()
            self._lost = asyncio.Event()
            try:
                async with (
                    streamablehttp_client(self.url, auth=self.auth.provider) as (r, w, _),
                    ClientSession(r, w) as session,
                ):
                    await session.initialize()
                    self.session = session
                    self.ready.set()
                    backoff = 5
                    self.log.info("Upstream MCP kapcsolat él: %s", self.url)
                    # addig tartjuk nyitva, amíg egy hívás nem jelzi, hogy elszállt
                    await self._lost.wait()
            except Exception as ex:  # noqa: BLE001
                self.log.warning(
                    "Upstream kapcsolat hiba (%s: %s) – újra %ss múlva", type(ex).__name__, ex, backoff
                )
            finally:
                self.session = None
                self.ready.clear()
            if not self.auth.logged_in.is_set():
                continue  # kijelentkeztek: várunk az új bejelentkezésre
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 120)

    def mark_lost(self) -> None:
        self._lost.set()


async def main() -> None:
    setup_logging()
    log = logging.getLogger("kifli.shim")

    url = os.environ.get("KIFLI_MCP_URL", "https://mcp.kifli.hu/mcp")
    data_dir = Path(os.environ.get("KIFLI_DATA_DIR", "/data"))
    sse_port = int(os.environ.get("KIFLI_PORT", "42783"))
    ingress_port = int(os.environ.get("KIFLI_INGRESS_PORT", "42784"))

    new_tools_enabled = os.environ.get("KIFLI_NEW_TOOLS_ENABLED", "false").lower() == "true"
    settings = ToolSettings(data_dir / "tool_settings.json", new_tools_enabled)
    auth = AuthManager(url, data_dir)
    upstream = Upstream(url, auth)

    async def on_login_ok() -> str:
        # megvárjuk, hogy az upstream kapcsolat is felálljon, és csak utána
        # töltetjük újra a HA MCP-integrációt, hogy már a toolokat lássa
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(upstream.ready.wait(), timeout=30)
        note = await reload_ha_mcp_entry(sse_port)
        log.info("HA MCP integráció újratöltés: %s", note)
        return note

    async def on_tools_saved() -> str:
        note = await reload_ha_mcp_entry(sse_port)
        log.info("Funkciólista mentve, HA MCP integráció újratöltés: %s", note)
        return note

    web = uvicorn.Server(
        uvicorn.Config(
            build_app(auth, sse_port, on_login_ok, settings, on_tools_saved),
            host="0.0.0.0",
            port=ingress_port,
            log_level="warning",
            proxy_headers=True,
            forwarded_allow_ips="*",
        )
    )
    web.install_signal_handlers = lambda: None  # type: ignore[method-assign]

    async def serve_web() -> None:
        try:
            await web.serve()
        except Exception as ex:  # noqa: BLE001
            log.error("Ingress oldal nem indult (%s) – a bejelentkező link a naplóban lesz.", ex)

    async def initial_login() -> None:
        try:
            await auth.ensure_logged_in()
            await on_login_ok()
        except Exception as ex:  # noqa: BLE001
            auth.status = "error"
            auth.error = f"{type(ex).__name__}: {ex}"
            log.error("Kifli OAuth bejelentkezés sikertelen: %s", auth.error)

    server = Server(SERVER_NAME)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        remote = upstream.session
        if remote is None:
            log.info("tools/list bejelentkezés nélkül → üres lista (nyisd meg az add-on oldalát)")
            return []
        try:
            res = await remote.list_tools()
        except Exception:
            upstream.mark_lost()
            raise
        out: list[types.Tool] = []

        # funkciólista nyilvántartása: új / megszűnt eszközök jelzése
        new, removed = settings.sync({(t.name or ""): (getattr(t, "description", "") or "") for t in res.tools})
        if new or removed:
            asyncio.get_running_loop().create_task(notify_ha(new, removed, settings))

        for t in res.tools:
            name = t.name or ""
            name_l = name.lower()

            if any(w in name_l for w in IGNORE_WORDS):
                continue

            if not settings.is_enabled(name):
                continue

            raw = getattr(t, "inputSchema", None) or getattr(t, "input_schema", None) or {}

            cooked = simplify_schema(raw)

            # ha mégis maradt nem-dict property, inkább dobjuk a tool-t
            if isinstance(cooked, dict) and _schema_has_non_dict_properties(cooked):
                continue

            # Alias kulccsal validáljuk, hogy biztosan inputSchema-ként menjen át
            out.append(
                types.Tool.model_validate(
                    {
                        "name": name,
                        "description": getattr(t, "description", "") or "",
                        "inputSchema": cooked,
                    }
                )
            )

        return out

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None = None):
        remote = upstream.session
        if remote is None:
            raise RuntimeError(
                "A Kifli MCP nincs bejelentkezve. Nyisd meg a 'Kifli MCP' oldalt a Home Assistant "
                "oldalsávjában, és jelentkezz be. / Not logged in to the Kifli MCP – open the "
                "'Kifli MCP' panel in the Home Assistant sidebar and sign in."
            )
        if not settings.is_enabled(name):
            raise RuntimeError(
                f"A(z) '{name}' Kifli-funkció ki van kapcsolva (Kifli MCP oldal → Funkciók). / "
                f"The Kifli tool '{name}' is disabled in the add-on."
            )
        args = dict(arguments or {})
        # Placeholder argot eldobjuk, mielőtt forwardolnánk a rohlik MCP felé.
        args.pop(PLACEHOLDER_ARG, None)
        try:
            return await remote.call_tool(name, args)
        except Exception:
            upstream.mark_lost()
            raise

    async def serve_stdio() -> None:
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            init = InitializationOptions(
                server_name=SERVER_NAME,
                server_version=SERVER_VERSION,
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            )
            await server.run(read_stream, write_stream, init)

    log.info(
        "Kifli schema shim %s indul (url=%s, ingress port=%s, data=%s)",
        SERVER_VERSION, url, ingress_port, data_dir,
    )
    async with anyio.create_task_group() as tg:
        tg.start_soon(serve_web)
        tg.start_soon(upstream.run)
        tg.start_soon(initial_login)
        await serve_stdio()
        tg.cancel_scope.cancel()


if __name__ == "__main__":
    anyio.run(main)
