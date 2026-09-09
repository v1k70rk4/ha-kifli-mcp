# Changelog

> 🇭🇺 **Magyarul a lap alján — [ugorj a magyar változatra](#magyar).**

## 1.2.1 — 2026-09-09

**Fixed — every MCP tool disappeared on Home Assistant 2026.9+**

Home Assistant 2026.9 replaced its schema converter (`voluptuous-openapi` → `probatio`). The new converter rewrites the draft 2020-12 *numeric* `exclusiveMinimum` / `exclusiveMaximum` into the obsolete draft-04 *boolean* form:

```
sent by the shim:        {"exclusiveMinimum": 0, "type": "integer"}
after HA converts it:    {"minimum": 0, "exclusiveMinimum": true, "type": "number"}
```

Draft 2020-12 requires a *number* there, so `true` is invalid. The Anthropic API rejects the **entire tool list** over one bad schema, which is why *all* tools vanished at once with:

```
tools.NN.custom.input_schema: JSON schema is invalid.
```

Three upstream tools carried numeric exclusive bounds: `add_products_to_shopping_list`, `remove_products_from_shopping_list`, `delete_shopping_list`.

- The shim now normalizes exclusive bounds before emitting them: `integer` types get the exact inclusive equivalent (`exclusiveMinimum: 0` → `minimum: 1`), other types keep the bound and drop the keyword.
- Verified against all 61 live tools through the real `probatio` round-trip: 3 schemas invalid before, 0 after, the other 58 unchanged.
- Internal: cleaned up all Ruff findings in the shim (no behaviour change).

The upstream schemas were valid throughout — this is a workaround for a converter regression, not a bug in the Rohlik Group MCP.

## 1.2.0 — 2026-06-25

- **Multi-country support.** New `country` option for the Rohlik Group endpoints: `hu` (Kifli.hu), `cz` (Rohlik.cz), `at` (Gurkerl.at), `de` (Knuspr.de), `ro` (Sezamo.ro).
- New optional `mcp_url` option to override the country-based endpoint.
- Renamed to *Rohlik Group (hu, cz, at, de, ro) MCP Connector*; bilingual documentation.
- Upgrading from a version without `country` defaults to `hu`, so existing setups keep working unchanged.

## 1.1.5 — 2026-01-25

- First public release: Rohlik Group MCP → SSE bridge for the Home Assistant MCP client.
- Built-in schema shim: inlines local `$ref`s, flattens unions, strips unsupported keywords, and fixes empty object `properties`.
- Add-on linting: dropped the default `boot` key and the deprecated `armv7` / `armhf` architectures.

---

<a name="magyar"></a>

# 🇭🇺 Változásnapló

## 1.2.1 — 2026-09-09

**Javítva — Home Assistant 2026.9+ alatt eltűnt az összes MCP tool**

A Home Assistant a 2026.9-ben lecserélte a séma-konvertert (`voluptuous-openapi` → `probatio`). Az új konverter a draft 2020-12-es *szám* alakú `exclusiveMinimum` / `exclusiveMaximum` kulcsot az elavult draft-04-es *boolean* alakra írja át:

```
amit a shim küld:        {"exclusiveMinimum": 0, "type": "integer"}
amit a HA csinál belőle: {"minimum": 0, "exclusiveMinimum": true, "type": "number"}
```

A draft 2020-12 ott *számot* vár, tehát a `true` érvénytelen. Az Anthropic API pedig egyetlen hibás séma miatt a **teljes toollistát** eldobja — ezért tűnt el *az összes* tool egyszerre, ezzel a hibával:

```
tools.NN.custom.input_schema: JSON schema is invalid.
```

Három tool hordozott szám alakú kizáró határt: `add_products_to_shopping_list`, `remove_products_from_shopping_list`, `delete_shopping_list`.

- A shim mostantól normalizálja a kizáró határokat, mielőtt kiengedi őket: `integer` típusnál pontos inkluzív megfelelőre (`exclusiveMinimum: 0` → `minimum: 1`), egyéb típusnál a határt megtartva elhagyja a kulcsot.
- Mind a 61 élő toolon ellenőrizve, valódi `probatio` körrel: előtte 3 séma volt érvénytelen, utána 0, a többi 58 változatlan.
- Belső: a shim összes Ruff-hibája javítva (viselkedés nem változott).

A sémák végig érvényesek voltak — ez egy konverter-regresszió megkerülése, nem a Rohlik Group MCP hibája.

## 1.2.0 — 2026-06-25

- **Több ország támogatása.** Új `country` opció a Rohlik Group végpontokhoz: `hu` (Kifli.hu), `cz` (Rohlik.cz), `at` (Gurkerl.at), `de` (Knuspr.de), `ro` (Sezamo.ro).
- Új, opcionális `mcp_url` beállítás az ország szerinti végpont felülírására.
- Átnevezve *Rohlik Group (hu, cz, at, de, ro) MCP Connector*-ra; kétnyelvű dokumentáció.
- Ha `country` opció nélküli verzióról frissítesz, az alapértelmezés `hu`, így a meglévő beállítás változatlanul működik tovább.

## 1.1.5 — 2026-01-25

- Első publikus kiadás: Rohlik Group MCP → SSE híd a Home Assistant MCP kliensének.
- Beépített schema shim: helyi `$ref`-ek beágyazása, uniók lapítása, nem támogatott kulcsok eltávolítása, üres object `properties` javítása.
- Add-on linter: az alapértelmezett `boot` kulcs és az elavult `armv7` / `armhf` architektúrák eltávolítva.
