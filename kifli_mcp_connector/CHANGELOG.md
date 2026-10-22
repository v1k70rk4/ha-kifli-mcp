# Changelog

> 🇭🇺 **Magyarul a lap alján — [ugorj a magyar változatra](#magyar).**

## 2.1.1 — 2026-10-23

**Fixed — the schema shim no longer loosens tool parameter limits**

The shim rewrites the upstream tool schemas into a form Home Assistant and the LLM APIs accept. In a few cases the rewritten schema allowed values the original did not:

- **`allOf`:** only the first part was kept, so the limits in the other parts were lost (e.g. a quantity that had to be at least 1 could be 0). Now every part counts: the tighter lower and upper bounds, all required fields and all properties are kept, and enums are intersected.
- **Draft-04 strict bounds** (`"minimum": 0, "exclusiveMinimum": true`): the strictness was dropped, so 0 was allowed. For integers the bound now becomes the next whole number (`minimum: 1`). For decimal numbers the bound stays inclusive, because the strict form is exactly what Home Assistant's converter breaks (see 1.2.1).
- **Strict bounds that are not whole numbers on integers** were rounded the wrong way (`exclusiveMaximum: 9.5` became `maximum: 8` instead of 9).

Only tool schemas that use these forms are affected; everything else is converted exactly as before. Found by CodeRabbit in the review of [#4](https://github.com/v1k70rk4/ha-kifli-mcp/pull/4).

## 2.1.0 — 2026-10-23

**New — turn individual Kifli tools on or off**

So a voice assistant can, for example, search, fill the cart and read orders, but cannot pay, book a timeslot or cancel an order.

- **Tools card** on the **Kifli MCP** sidebar page, with a checkbox per upstream tool. Unchecked tools are left out of the tool list Home Assistant sees **and refused when called**, so they cannot be used even by a client that connects to the SSE port directly.
- Saving reloads the Home Assistant MCP integration, so the change is live within seconds. If that reload fails, the page says so instead of reporting success.
- **Nothing disappears on update:** on the first start every tool currently offered is enabled.
- **New or removed upstream tools are reported once:** a persistent notification, plus the `kifli_mcp_new_tool` / `kifli_mcp_removed_tool` events for automations. New tools start **disabled** unless the new `new_tools_enabled` option is on.
- A tool that disappears upstream for a while keeps its on/off setting when it comes back.
- If the settings file (`/data/tool_settings.json`) is ever corrupted, every tool is treated as new instead of all being switched on: with the default `new_tools_enabled: false` they come in disabled, with a notification. The broken file is kept as `tool_settings.corrupt`.
- Tool descriptions on the page are shown in Hungarian when `country` is `hu` (the model still gets the upstream text).
- Docs: the SSE port has no authentication of its own – the *Networking & security* section explains how to keep it internal.

Thanks to [@wenandras](https://github.com/wenandras) for the feature and for testing it on a Home Assistant Green with a live account ([#3](https://github.com/v1k70rk4/ha-kifli-mcp/pull/3)).

## 2.0.1 — 2026-10-22

**Fixed — the add-on did not build on aarch64 (e.g. Home Assistant Green)**

The Dockerfile defaulted `BUILD_FROM` to the `amd64` base image. The add-on has no `build.yaml` (the current Supervisor flags it as deprecated), so the Supervisor only passes `BUILD_ARCH`, and on ARM the build stopped with:

```
ERROR: failed to solve: ghcr.io/home-assistant/amd64-base:latest: ... no match for platform in manifest: not found
```

- The base image is now derived from `BUILD_ARCH` (`ghcr.io/home-assistant/${BUILD_ARCH}-base:latest`), so `amd64` and `aarch64` each build on their own base image.
- No change on `amd64`.

Thanks to [@wenandras](https://github.com/wenandras) for the fix and for testing it on a Home Assistant Green ([#1](https://github.com/v1k70rk4/ha-kifli-mcp/pull/1)).

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

## 2.1.1 — 2026-10-23

**Javítva — a schema shim már nem lazít az eszközök paraméterkorlátain**

A shim az upstream eszközök sémáit olyan alakra írja át, amit a Home Assistant és az LLM API-k elfogadnak. Néhány esetben az átírt séma olyan értéket is megengedett, amit az eredeti nem:

- **`allOf`:** csak az első rész maradt meg, így a többi rész korlátai elvesztek (pl. egy legalább 1 értékű mennyiség 0 is lehetett). Most minden rész számít: a szigorúbb alsó és felső határ, az összes kötelező mező és tulajdonság megmarad, az enumokból a metszet.
- **Draft-04-es kizáró határ** (`"minimum": 0, "exclusiveMinimum": true`): a kizárás elveszett, így a 0 is megengedett lett. Egésznél a határ most a következő egész szám (`minimum: 1`). Tört számnál a határ inkluzív marad, mert a kizáró alakot pont a Home Assistant konvertere rontja el (lásd 1.2.1).
- **Egész típusnál a nem egész kizáró határok** rossz irányba kerekítődtek (`exclusiveMaximum: 9.5`-ből `maximum: 8` lett 9 helyett).

Csak az ilyen alakot használó eszközsémákat érinti; minden más pontosan úgy alakul át, mint eddig. A CodeRabbit találta a [#4](https://github.com/v1k70rk4/ha-kifli-mcp/pull/4) review-jában.

## 2.1.0 — 2026-10-23

**Új — a Kifli-funkciók egyenként ki/be kapcsolhatók**

Így a hangasszisztens például kereshet, kosárba tehet és láthatja a rendeléseket, de fizetni, idősávot foglalni vagy rendelést lemondani nem tud.

- **Funkciók kártya** a **Kifli MCP** oldalon az oldalsávban, minden upstream eszköz mellett egy jelölőnégyzettel. A kikapcsolt funkció kimarad a Home Assistant által látott listából, **és hívásra is elutasítja** az add-on, így akkor sem használható, ha valaki közvetlenül az SSE portra csatlakozik.
- Mentéskor a HA MCP-integráció újratöltődik, a változás másodperceken belül él. Ha az újratöltés nem sikerül, az oldal ezt jelzi, nem sikert.
- **Frissítéskor semmi nem tűnik el:** az első induláskor minden épp elérhető funkció bekapcsolt.
- **Új vagy megszűnt upstream funkcióról egyszer szól:** állandó értesítés, valamint `kifli_mcp_new_tool` / `kifli_mcp_removed_tool` esemény automatizáláshoz. Az új funkció **kikapcsolva** érkezik, hacsak az új `new_tools_enabled` opció nincs bekapcsolva.
- Ha egy funkció egy időre eltűnik az upstreamről, visszatéréskor megtartja a ki/be állapotát.
- Ha a beállításfájl (`/data/tool_settings.json`) valaha megsérülne, nem kapcsol be minden, hanem minden funkciót újnak tekint: az alapértelmezett `new_tools_enabled: false` mellett kikapcsolva érkeznek, értesítéssel. A hibás fájl `tool_settings.corrupt` néven megmarad.
- `country: hu` esetén az oldalon magyar eszközleírások látszanak (a modell továbbra is az eredeti leírást kapja).
- Dokumentáció: az SSE portnak nincs saját hitelesítése – a *Hálózat és biztonság* rész leírja, hogyan tartható belső használatban.

Köszönjük [@wenandras](https://github.com/wenandras) funkcióját és a Home Assistant Greenen, éles fiókkal végzett tesztet ([#3](https://github.com/v1k70rk4/ha-kifli-mcp/pull/3)).

## 2.0.1 — 2026-10-22

**Javítva — az add-on nem buildelt aarch64-en (pl. Home Assistant Green)**

A Dockerfile a `BUILD_FROM`-ban alapértelmezésként az `amd64` alapképet használta. Az add-onnak nincs `build.yaml`-ja (a mostani Supervisor elavultnak jelzi), így a Supervisor csak a `BUILD_ARCH`-ot adja át, ARM-on pedig ezzel állt meg a build:

```
ERROR: failed to solve: ghcr.io/home-assistant/amd64-base:latest: ... no match for platform in manifest: not found
```

- Az alapkép most a `BUILD_ARCH`-ból képződik (`ghcr.io/home-assistant/${BUILD_ARCH}-base:latest`), így az `amd64` és az `aarch64` is a saját alapképére épül.
- `amd64`-en nincs változás.

Köszönjük [@wenandras](https://github.com/wenandras) javítását és a Home Assistant Greenen végzett tesztet ([#1](https://github.com/v1k70rk4/ha-kifli-mcp/pull/1)).

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
