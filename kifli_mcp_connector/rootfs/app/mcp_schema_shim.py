#!/usr/bin/env python3
from __future__ import annotations

import copy
import os
from typing import Any

import anyio
import mcp.server.stdio
import mcp.types as types
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

SERVER_NAME = "kifli-schema-shim"
SERVER_VERSION = "1.0.2"

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
    for _, v in props.items():
        if not isinstance(v, dict):
            return True
    return False


def simplify_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
    base = copy.deepcopy(schema) if isinstance(schema, dict) else {}

    base = _inline_local_refs(base)
    base = _normalize_unions(base)
    base = _strip_dollar_keys(base)
    base = _strip_unsupported_keywords(base)
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


async def main() -> None:
    url = os.environ.get("KIFLI_MCP_URL", "https://mcp.kifli.hu/mcp")
    transport = os.environ.get("KIFLI_TRANSPORT", "http-first")

    email = os.environ.get("RHL_EMAIL") or ""
    password = os.environ.get("RHL_PASS") or ""
    if not email or email == "null":
        raise SystemExit("RHL_EMAIL nincs beállítva")
    if not password or password == "null":
        raise SystemExit("RHL_PASS nincs beállítva")

    remote_params = StdioServerParameters(
        command="mcp-remote",
        args=[
            url,
            "--transport",
            transport,
            "--header",
            f"rhl-email:{email}",
            "--header",
            f"rhl-pass:{password}",
            "--silent",
        ],
        env=os.environ.copy(),
    )

    server = Server(SERVER_NAME)

    async with stdio_client(remote_params) as (r_read, r_write):
        async with ClientSession(r_read, r_write) as remote:
            await remote.initialize()

            @server.list_tools()
            async def list_tools() -> list[types.Tool]:
                res = await remote.list_tools()
                out: list[types.Tool] = []

                for t in res.tools:
                    name = t.name or ""
                    name_l = name.lower()

                    if any(w in name_l for w in IGNORE_WORDS):
                        continue

                    raw = (
                        getattr(t, "inputSchema", None)
                        or getattr(t, "input_schema", None)
                        or {}
                    )

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
                args = dict(arguments or {})
                # Placeholder argot eldobjuk, mielőtt forwardolnánk a rohlik MCP felé.
                args.pop(PLACEHOLDER_ARG, None)
                return await remote.call_tool(name, args)

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


if __name__ == "__main__":
    anyio.run(main)
