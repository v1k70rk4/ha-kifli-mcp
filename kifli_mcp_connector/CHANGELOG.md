# Changelog

> 🇭🇺 **Magyarul a lap alján — [ugorj a magyar változatra](#magyar).**

## 2.1.0 — 2026-10-22

**New — turn individual tools on/off, and get notified when the tool list changes**

- **Tools card on the Kifli MCP page:** every upstream tool with its description and a checkbox. Unchecked tools are removed from `tools/list` *and* refused in `tools/call`, so they cannot be called even by a client that talks to the SSE port directly. Saving reloads the Home Assistant MCP integration.
- **New / removed tools are reported once:** a persistent notification plus the `kifli_mcp_new_tool` (`tool`, `description`, `enabled`) and `kifli_mcp_removed_tool` (`tool`) events, so an automation can forward them (Telegram, mobile push, …).
- **New option `new_tools_enabled`** (default `false`): whether tools that appear upstream later start enabled. On the first start after the update every tool currently offered is enabled, so nothing disappears for existing installs.
- State lives in `/data/tool_settings.json`.

## 2.0.1 — 2026-10-22

**Fixed — the add-on did not build on aarch64 (e.g. Home Assistant Green)**

The Dockerfile defaulted `BUILD_FROM` to the amd64 base image and the add-on had no `build.yaml`, so the Supervisor (which only passes `BUILD_ARCH`) built on top of `amd64-base` and failed on ARM with `no match for platform in manifest`. The base image is now derived from `BUILD_ARCH` in the Dockerfile (no `build.yaml`, which the Supervisor now reports as deprecated).

## 2.0.0 — 2026-10-16

**Breaking — sign-in is now OAuth; the `email` / `password` options are gone**

In October 2026 the Rohlik Group switched off the `rhl-email` / `rhl-pass` header login on its MCP servers. The endpoint now answers every request with:

```
401 RHL-EMAIL/RHL-PASS header login is obsolete and no longer supported. Authenticate with OAuth instead.
```

With 1.x this showed up in Home Assistant as `Timeout when listing tools` on the MCP integration and `Error getting LLM API … not found` in Assist, because the bundled `mcp-remote` sat waiting for a browser that never came.

- **OAuth 2.1 (PKCE) sign-in** using the MCP Python SDK's built-in client: discovery, dynamic client registration, token exchange and **automatic refresh** (`offline_access` is requested explicitly). Tokens live in `/data/oauth/`.
- **New "Kifli MCP" sidebar page (ingress)** to sign in. The identity server only allows a `localhost` redirect, so after logging in you paste the `http://localhost:3334/oauth/callback?code=…` URL your browser lands on into the page – it is a two-step, one-time process.
- After a successful sign-in the add-on **reloads the Home Assistant MCP integration** itself (`homeassistant_api`), so the tools appear within seconds instead of at the next 30-minute poll.
- While not signed in the shim returns an **empty tool list** instead of hanging, so Assist keeps working and the integration no longer sits in `setup_retry`.
- **Removed:** Node.js and `mcp-remote` (smaller image), `host_network` (the SSE port is mapped instead), the `email` / `password` options (kept in the schema as optional no-ops so existing configurations still validate – delete them).

Update, start the add-on, open **Kifli MCP** in the sidebar, sign in once.

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

## 2.1.0 — 2026-10-22

**Új — funkciónkénti ki/be kapcsolás, és értesítés, ha változik a funkciólista**

- **Funkciók kártya a Kifli MCP oldalon:** minden upstream eszköz leírással és jelölőnégyzettel. A kikapcsolt eszköz kimarad a `tools/list`-ből, *és* a `tools/call` is elutasítja, így akkor sem hívható, ha valaki közvetlenül az SSE portra csatlakozik. Mentéskor a HA MCP-integráció újratöltődik.
- **Az új / megszűnt eszközökről egyszer szól:** állandó értesítés, valamint `kifli_mcp_new_tool` (`tool`, `description`, `enabled`) és `kifli_mcp_removed_tool` (`tool`) esemény, amit automatizálás továbbíthat (Telegram, mobil értesítés stb.).
- **Új `new_tools_enabled` opció** (alap: `false`): a később megjelenő eszközök bekapcsolva érkezzenek-e. A frissítés utáni első induláskor minden épp elérhető eszköz bekapcsolt, így a meglévő telepítéseknél semmi nem tűnik el.
- Az állapot a `/data/tool_settings.json`-ban van.

## 2.0.1 — 2026-10-22

**Javítva — aarch64-en (pl. Home Assistant Green) nem épült le az add-on**

A Dockerfile alapból az amd64 alapképet használta, `build.yaml` pedig nem volt, így a Supervisor (ami csak a `BUILD_ARCH`-ot adja át) ARM-on is az `amd64-base`-ből próbált építeni, és `no match for platform in manifest` hibával elhasalt. Az alapkép most a Dockerfile-ban a `BUILD_ARCH`-ból képződik (`build.yaml` nélkül, mert azt a Supervisor már elavultnak jelzi).

## 2.0.0 — 2026-10-16

**Törő változás — a bejelentkezés OAuth lett; az `email` / `password` opciók megszűntek**

2026 októberében a Rohlik Group kikapcsolta az `rhl-email` / `rhl-pass` fejléces bejelentkezést az MCP-szerverein. A végpont azóta minden kérésre ezt adja:

```
401 RHL-EMAIL/RHL-PASS header login is obsolete and no longer supported. Authenticate with OAuth instead.
```

Az 1.x-szel ez a Home Assistantban `Timeout when listing tools` hibaként jelent meg az MCP-integráción, az Assistban pedig `Error getting LLM API … not found`-ként, mert a beépített `mcp-remote` egy böngészőre várt, ami sosem jött.

- **OAuth 2.1 (PKCE) bejelentkezés** az MCP Python SDK beépített kliensével: felfedezés, dinamikus kliensregisztráció, token csere és **automatikus frissítés** (az `offline_access` scope-ot kifejezetten kérjük). A tokenek a `/data/oauth/` alatt vannak.
- **Új „Kifli MCP” oldal az oldalsávban (ingress)** a bejelentkezéshez. Az identity-szerver csak `localhost` visszahívást enged, ezért bejelentkezés után a böngésző által mutatott `http://localhost:3334/oauth/callback?code=…` címet kell bemásolni az oldalra – kétlépéses, egyszeri folyamat.
- Sikeres bejelentkezés után az add-on **maga újratölti a Home Assistant MCP-integrációját** (`homeassistant_api`), így a toolok másodperceken belül megjelennek, nem a következő 30 perces lekérdezésnél.
- Amíg nincs bejelentkezve, a shim **üres tool-listát** ad lógás helyett, így az Assist működik tovább, és az integráció nem ragad `setup_retry`-ban.
- **Eltávolítva:** Node.js és `mcp-remote` (kisebb image), a `host_network` (helyette port-mappelés), az `email` / `password` opciók (a sémában opcionális, hatástalan kulcsként maradtak, hogy a meglévő konfiguráció érvényes maradjon – töröld őket).

Frissíts, indítsd el az add-ont, nyisd meg a **Kifli MCP** oldalt az oldalsávban, jelentkezz be egyszer.

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
