> 🇭🇺 **Magyar leírás a lap alján — [ugorj a magyar változatra](#magyar).**

# Rohlik Group (hu, cz, at, de, ro) MCP Connector

**Rohlik Group MCP → SSE bridge** for Home Assistant, with a built-in **schema shim**.

> ⚠️ **Unofficial / community add-on.** Not affiliated with, endorsed by, or operated by Rohlik Group. You use your own account credentials at your own risk.

This add-on exposes the Rohlik Group MCP tools (Kifli.hu, Rohlik.cz, Gurkerl.at, Knuspr.de, Sezamo.ro) on an **SSE endpoint** that Home Assistant can consume directly, while a **schema shim** normalizes the tool input schemas to satisfy the stricter Home Assistant / OpenAI function-tooling expectations.

## What you get
- OAuth 2.1 (PKCE) sign-in to the Kifli / Rohlik Group MCP (HU/CZ/AT/DE/RO) with automatic token refresh
- A **Kifli MCP** page in the Home Assistant sidebar (ingress) to sign in – no credentials stored in the add-on
- `mcp-proxy` SSE server towards Home Assistant
- `mcp_schema_shim.py`: schema normalization (refs, unions, unsupported keys, empty-object-properties fix, draft-04 exclusive bounds)
- **Per-tool on/off switches** on the Kifli MCP page, and a notification when the upstream tool list changes (see *Tools*)

## How it works
```
Home Assistant (MCP client)
        │  SSE  →  http://<ha-ip>:42783/sse
        ▼
   mcp-proxy ──stdio──► mcp_schema_shim.py ──HTTPS (OAuth Bearer)──► Rohlik Group MCP
                              │
                              └── ingress page "Kifli MCP" (sign-in)
```

Since October 2026 the Rohlik Group MCP only accepts **OAuth 2.1** tokens (the old `rhl-email` / `rhl-pass` header login was switched off server-side). The add-on registers itself as an OAuth client, you sign in once in your browser, and the token is refreshed automatically from then on.

## Prerequisites
- A working **Rohlik Group account** in your country (e.g. Kifli.hu for `hu`, Rohlik.cz for `cz`, …).

## Installation
1. Add the repository:
   - `https://github.com/v1k70rk4/ha-kifli-mcp`
2. Install from the Add-on Store: **Rohlik Group (hu, cz, at, de, ro) MCP Connector**
3. Pick your `country`, start the add-on.
4. Open **Kifli MCP** in the Home Assistant sidebar and sign in (see below).

### Signing in (OAuth)
The Rohlik identity server only allows a `http://localhost:…` redirect for the sign-in, but the add-on runs on your Home Assistant box without a browser – so the last step is a copy-paste:

1. On the **Kifli MCP** sidebar page click **Sign in**. Log in at `identity.kifli.hu` (same account as the web shop).
2. Your browser is redirected to `http://localhost:3334/oauth/callback?code=…&state=…` and shows **"This site can't be reached"**. That is expected.
3. Copy the **whole URL** from the address bar and paste it into the box on the Kifli MCP page, then **Submit**.
4. The add-on exchanges the code for a token, stores it under `/data/oauth/` and reloads the Home Assistant MCP integration, so the tools appear within seconds.

Until you sign in the add-on serves an **empty tool list** (instead of timing out), so the rest of Assist keeps working. If the token ever becomes invalid, the page shows the sign-in again. **Log out** on the page deletes the stored token.

## Configuration

### Options
| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `port` | int | `42783` | SSE server port |
| `country` | list | `hu` | Rohlik Group country: `hu`, `cz`, `at`, `de`, `ro` (see below) |
| `mcp_url` | string | `""` | (Optional) Custom MCP endpoint; overrides the `country`-based URL |
| `new_tools_enabled` | bool | `false` | Whether tools that appear upstream **later** start enabled (see *Tools*) |
| `email`, `password` | – | – | **Deprecated since 2.0**, ignored. Left in the schema only so old configurations still validate – you can delete them. |

### Example
```yaml
port: 42783
country: "hu"
```

### Supported countries (Rohlik Group)
The `country` option points to that country's MCP endpoint. Sign in with **an account of that country's service**.

| `country` | Brand | MCP endpoint |
|-----------|-------|--------------|
| `hu` | Kifli.hu (Hungary) | `https://mcp.kifli.hu/mcp` |
| `cz` | Rohlik.cz (Czechia) | `https://mcp.rohlik.cz/mcp` |
| `at` | Gurkerl.at (Austria) | `https://mcp.gurkerl.at/mcp` |
| `de` | Knuspr.de (Germany) | `https://mcp.knuspr.de/mcp` |
| `ro` | Sezamo.ro (Romania) | `https://mcp.sezamo.ro/mcp` |

> Rohlik Group does not operate a service in Slovakia. If you have a new or unlisted endpoint, set the `mcp_url` option — it overrides the `country` default.
>
> Upgrading from a version without the `country` option defaults to Hungary (`hu`), so existing setups keep working without any change.

The SSE endpoint (by default): `http://<home_assistant_ip>:42783/sse`

### Add the MCP server (Devices & Services)
1. Home Assistant: **Settings → Devices & Services**
2. **Add Integration**
3. Search for: **Model Context Protocol (MCP)**
4. Enter the MCP SSE URL:
   - `http://<home_assistant_ip>:42783/sse`
5. Save and wait until the integration picks up the tools.

### Add MCP to Assist
1. Home Assistant: **Settings → Voice assistants (Assist)**
2. Open the assistant you use (e.g. "OpenAI")
3. Under **Control Home Assistant**, enable the **rohlik_mcp** integration
4. Save.

### Recommended prompt (Assistant instructions)
Paste into the *instructions* field of your Assist / OpenAI assistant:

```text
If the user asks anything shopping-related (product search, categories, cart, favorites, ordering), you MUST use the Rohlik/Kifli MCP tools and never guess.

Before every shopping action:
- first find the relevant product(s) with the MCP tools,
- only then add to / modify the cart based on the results, or ask for a missing parameter.

If the request is ambiguous (quantity, package size, brand, budget), ask 1 short follow-up question, then use the tools.
Report cart or order state only from the MCP; do not make assumptions.
If the user is not talking about the shop, do not use the MCP.
Strip image links from the answers — the system cannot display them.
```

## Tools (turning features on/off)
The **Tools** card on the Kifli MCP page lists every tool the Rohlik Group MCP offers, with a checkbox each (descriptions are shown in Hungarian when `country` is `hu`).

- Only checked tools are passed to Home Assistant. Unchecked tools are also **refused in `tools/call`**, so they cannot be used even by a client that connects to the SSE port directly.
- Saving reloads the Home Assistant MCP integration, so the change is live within seconds.
- On the first start after updating, every tool currently offered is enabled — nothing disappears for existing installs.
- A tool that appears upstream later starts **disabled** (unless `new_tools_enabled: true`) and you get a persistent notification, plus these events for automations (e.g. to forward to Telegram or a phone):
  - `kifli_mcp_new_tool` — `tool`, `description`, `enabled`
  - `kifli_mcp_removed_tool` — `tool`

  If Home Assistant cannot be reached at that moment, the notification and the events are kept and retried at the next tool listing, so they are not lost (in rare cases an event may arrive twice). Each report is a separate notification.
- A save from a page that was loaded before another change is rejected ("reload and save again"), so an old browser tab cannot overwrite newer settings.
- Settings live in `/data/tool_settings.json`. Scripted changes: `POST` to the ingress path `tools` with JSON `{"enabled": ["tool_a", ...]}`.

Example: keep payment, ordering and timeslot booking manual by unchecking e.g. `update_payment_method_checkout`, `reserve_timeslot`, `repeat_order`, `cancel_order`, `submit_claim` — the assistant can still search, fill the cart and read orders, timeslots and the checkout.

## Networking & security
- The add-on listens on port **42783** (SSE at `/sse`, mapped to the host) and serves the sign-in page through Home Assistant **ingress** only.
- The SSE endpoint has **no authentication of its own**: anyone who can reach port 42783 can use your signed-in Kifli account. If only the Home Assistant on the same box uses it, you can clear the host port in the add-on's *Network* settings and point the MCP integration at the internal hostname instead: `http://<add-on hostname>:42783/sse` (the add-on slug with `_` replaced by `-`, e.g. `xxxxxxxx-kifli-mcp-connector`).
- No password is stored: the add-on keeps an OAuth access/refresh token under `/data/oauth/` (mode 600) and uses it as a Bearer token over HTTPS.
- `homeassistant_api: true` is used for one thing: reloading the MCP integration after a successful sign-in.

## Supported architectures
`amd64`, `aarch64`. (`armv7` / `armhf` were removed — unsupported by Home Assistant since 2025.12.)

## Troubleshooting
- **No tools, Assist says the Kifli MCP is not signed in:** open **Kifli MCP** in the sidebar and complete the sign-in (see *Signing in*). Until then the tool list is deliberately empty.
- **The browser says "can't reach localhost:3334" after login:** that is the normal last step – copy the URL and paste it on the Kifli MCP page.
- **"RHL-EMAIL/RHL-PASS header login is obsolete" in the log / `Timeout when listing tools` in Home Assistant:** you are on 1.x; update to 2.0 and sign in via OAuth.
- **No tools appear in Home Assistant:** confirm the add-on is running and the SSE URL is exactly `http://<ha-ip>:42783/sse`; reload the MCP integration.
- **Check the logs:** the startup line logs the resolved `country` and `url`, so you can verify the correct endpoint is being used.
- **Every MCP tool disappears at once, and the LLM errors with `tools.NN.custom.input_schema: JSON schema is invalid` (Home Assistant 2026.9+):**
  Fixed in add-on **1.2.1** — update and restart the add-on.

  Home Assistant 2026.9 replaced its schema converter (`voluptuous-openapi` → `probatio`). The new converter's `from_openapi()` / `to_openapi()` round-trip rewrites the draft 2020-12 **numeric** `exclusiveMinimum` / `exclusiveMaximum` into the obsolete draft-04 **boolean** form:

  ```
  sent by the shim:   {"exclusiveMinimum": 0, "type": "integer"}
  after HA converts:  {"minimum": 0, "exclusiveMinimum": true, "type": "number"}
  ```

  Under draft 2020-12 `exclusiveMinimum` must be a *number*, so `true` is invalid. The Anthropic API rejects the **entire tool list** over a single bad schema — which is why *all* tools vanish, not just the affected ones. Three upstream tools carried numeric exclusive bounds: `add_products_to_shopping_list`, `remove_products_from_shopping_list`, `delete_shopping_list`.

  The upstream schemas were valid the whole time; this is a workaround for the converter regression. The shim now normalizes exclusive bounds before they leave: for `integer` it uses the exact inclusive equivalent (`exclusiveMinimum: 0` → `minimum: 1`), for other types it keeps the bound and drops the keyword.

---

<a name="magyar"></a>

# 🇭🇺 Magyar — Rohlik Group (hu, cz, at, de, ro) MCP Connector

**Rohlik Group MCP → SSE bridge** Home Assistant környezethez, beépített **schema shim**-mel.

> ⚠️ **Nem hivatalos / közösségi add-on.** Nem áll kapcsolatban a Rohlik Grouppal, és nem a Rohlik Group üzemelteti. A saját fiókod adatait saját felelősségre használod.

Az add-on célja, hogy a Rohlik Group MCP tooljait (Kifli.hu, Rohlik.cz, Gurkerl.at, Knuspr.de, Sezamo.ro) egy Home Assistantból egyszerűen elérhető **SSE endpointon** tegye elérhetővé, miközben a tool input schema-kat „megszelídíti” a Home Assistant / OpenAI function tooling elvárásaihoz.

## Mit kapsz?
- OAuth 2.1 (PKCE) bejelentkezés a Kifli / Rohlik Group MCP felé (HU/CZ/AT/DE/RO), automatikus token-frissítéssel
- **Kifli MCP** oldal a Home Assistant oldalsávjában (ingress) a bejelentkezéshez – jelszó nem tárolódik az add-onban
- `mcp-proxy` SSE szerver a Home Assistant felé
- `mcp_schema_shim.py`: schema normalizálás (refs, unions, unsupported kulcsok, üres object properties fix, draft-04 kizáró határok)
- **Funkciónkénti ki/be kapcsolás** a Kifli MCP oldalon, és értesítés, ha változik az upstream funkciólista (lásd *Funkciók*)

## Hogyan működik?
```
Home Assistant (MCP kliens)
        │  SSE  →  http://<ha-ip>:42783/sse
        ▼
   mcp-proxy ──stdio──► mcp_schema_shim.py ──HTTPS (OAuth Bearer)──► Rohlik Group MCP
                              │
                              └── ingress oldal „Kifli MCP” (bejelentkezés)
```

2026 októberétől a Rohlik Group MCP csak **OAuth 2.1** tokent fogad el (a régi `rhl-email` / `rhl-pass` fejléces bejelentkezést szerveroldalon kikapcsolták). Az add-on regisztrálja magát OAuth-kliensként, te egyszer bejelentkezel a böngésződben, a tokent onnantól automatikusan frissíti.

## Előfeltételek
- Működő **Rohlik Group fiók** a saját országodban (pl. `hu`-hoz Kifli.hu, `cz`-hez Rohlik.cz, …).

## Telepítés
1. Add hozzá a repository-t:
   - `https://github.com/v1k70rk4/ha-kifli-mcp`
2. Add-on Store-ban telepítsd: **Rohlik Group (hu, cz, at, de, ro) MCP Connector**
3. Válaszd ki a `country`-t, indítsd el az add-ont.
4. Nyisd meg a **Kifli MCP** oldalt a Home Assistant oldalsávjában, és jelentkezz be (lásd lent).

### Bejelentkezés (OAuth)
A Rohlik identity-szervere csak `http://localhost:…` visszahívási címet enged a bejelentkezéshez, az add-on viszont a Home Assistant gépen, böngésző nélkül fut – ezért az utolsó lépés egy másolás-beillesztés:

1. A **Kifli MCP** oldalon kattints a **Bejelentkezés** gombra. Jelentkezz be az `identity.kifli.hu` oldalon (ugyanaz a fiók, mint a webshopban).
2. A böngésző a `http://localhost:3334/oauth/callback?code=…&state=…` címre irányít, és azt írja, hogy **„nem lehet elérni az oldalt”**. Ez így normális.
3. Másold ki a **teljes címet** a címsorból, illeszd be a Kifli MCP oldal mezőjébe, majd **Beküldés**.
4. Az add-on tokenre cseréli a kódot, elmenti a `/data/oauth/` alá, és újratölti a Home Assistant MCP-integrációját – a toolok másodperceken belül megjelennek.

Amíg nem jelentkezel be, az add-on **üres tool-listát** ad (nem időtúllépést), így az Assist többi része zavartalanul működik. Ha a token valaha érvénytelenné válik, az oldal újra a bejelentkezést mutatja. A **Kijelentkezés** gomb törli a tárolt tokent.

## Konfiguráció

### Opciók
| Kulcs | Típus | Alap | Leírás |
|------|------|------|--------|
| `port` | int | `42783` | SSE szerver port |
| `country` | list | `hu` | Rohlik Group ország: `hu`, `cz`, `at`, `de`, `ro` (lásd lentebb) |
| `mcp_url` | string | `""` | (Opcionális) Egyedi MCP végpont; ha kitöltöd, felülírja a `country` szerinti URL-t |
| `new_tools_enabled` | bool | `false` | Az upstream listán **később** megjelenő funkciók bekapcsolva érkezzenek-e (lásd *Funkciók*) |
| `email`, `password` | – | – | **2.0 óta elavult**, figyelmen kívül marad. Csak azért van a sémában, hogy a régi konfiguráció ne akadjon fenn az ellenőrzésen – nyugodtan töröld. |

### Példa
```yaml
port: 42783
country: "hu"
```

### Támogatott országok (Rohlik Group)
A `country` opció a megfelelő ország MCP végpontjára mutat. **Az adott ország szolgáltatásához tartozó fiókkal** jelentkezz be.

| `country` | Márka | MCP végpont |
|-----------|-------|-------------|
| `hu` | Kifli.hu (Magyarország) | `https://mcp.kifli.hu/mcp` |
| `cz` | Rohlik.cz (Csehország) | `https://mcp.rohlik.cz/mcp` |
| `at` | Gurkerl.at (Ausztria) | `https://mcp.gurkerl.at/mcp` |
| `de` | Knuspr.de (Németország) | `https://mcp.knuspr.de/mcp` |
| `ro` | Sezamo.ro (Románia) | `https://mcp.sezamo.ro/mcp` |

> Szlovákiában a Rohlik Group nem üzemeltet saját szolgáltatást. Ha új vagy nem listázott végpontod van, töltsd ki az `mcp_url` opciót — az felülírja a `country` szerinti alapértelmezést.
>
> Ha egy `country` opció nélküli verzióról frissítesz, az alapértelmezés a magyar (`hu`), így a meglévő beállításod változatlanul működik tovább.

Az SSE endpoint (alapesetben): `http://<home_assistant_ip>:42783/sse`

### MCP szerver felvétele (Eszközök és szolgáltatások)
1. Home Assistant: **Beállítások → Eszközök és szolgáltatások**
2. **Integráció hozzáadása**
3. Keresd meg: **Model Context Protocol (MCP)**
4. Add meg az MCP SSE URL-t:
   - `http://<home_assistant_ip>:42783/sse`
5. Mentsd el, várd meg míg az integráció felveszi a toolokat.

### MCP hozzáadása az Assisthoz
1. Home Assistant: **Beállítások → Hangsegédek (Assist)**
2. Nyisd meg a használt asszisztenst (pl. „OpenAI")
3. Az instrukciók alatt a **Home Assistant vezérlése** résznél engedélyezd a **rohlik_mcp** integrációt
4. Mentsd el.

### Ajánlott prompt (Assistant instructions)
Másold be az Assist / OpenAI asszisztens *instructions* mezőjébe:

```text
Ha a felhasználó bármilyen vásárlással kapcsolatos dolgot kér (termékkeresés, kategóriák, kosár, kedvencek, rendelés), akkor KÖTELEZŐEN használd a Kifli MCP eszközöket (toolokat), és ne találgass.

Minden Kifli művelet előtt:
- először keresd meg a releváns termék(ek)et az MCP toolokkal,
- majd csak a találatok alapján tegyél kosárba / módosíts kosarat / kérdezz rá hiányzó paraméterre.

Ha a kérés többértelmű (mennyiség, kiszerelés, márka, budget), kérdezz vissza 1 rövid kérdéssel, majd toolozz.
A kosár vagy rendelés állapotát csak MCP-ből mondd meg, feltételezést nem adhatsz.
Ha a felhasználó nem a Kifliről beszél, akkor ne használd az MCP-t.
A válaszokból szedd ki a kép hivatkozást, azokat a rendszer nem tudja megjeleníteni.
```

## Funkciók (ki/be kapcsolás)
A Kifli MCP oldal **Funkciók** kártyája a Rohlik Group MCP összes eszközét felsorolja, mindegyik mellett egy jelölőnégyzettel (`country: hu` esetén magyar leírással).

- Csak a bepipált funkciókat kapja meg a Home Assistant. A kikapcsoltat a **`tools/call` is elutasítja**, így akkor sem használható, ha valaki közvetlenül az SSE portra csatlakozik.
- Mentéskor a HA MCP-integráció újratöltődik, a változás másodperceken belül él.
- A frissítés utáni első induláskor minden épp elérhető funkció bekapcsolt – a meglévő telepítéseknél semmi nem tűnik el.
- A később megjelenő funkció **kikapcsolva** érkezik (hacsak nem `new_tools_enabled: true`), és állandó értesítés jön róla, valamint automatizáláshoz ezek az események (pl. Telegramra vagy telefonra továbbításhoz):
  - `kifli_mcp_new_tool` — `tool`, `description`, `enabled`
  - `kifli_mcp_removed_tool` — `tool`

  Ha a Home Assistant éppen nem érhető el, az értesítés és az események megmaradnak, és a következő eszközlistázáskor újra kimennek, így nem vesznek el (ritkán egy esemény kétszer is megérkezhet). Minden jelzés külön értesítés.
- Ha az oldalt egy másik módosítás előtt töltötted be, a mentést elutasítja („frissítsd az oldalt, és mentsd újra”), így egy régi böngészőfül nem írhatja felül az újabb beállítást.
- A beállítás a `/data/tool_settings.json`-ban van. Gépi módosítás: `POST` az ingress `tools` útvonalra, JSON-nal: `{"enabled": ["tool_a", ...]}`.

Példa: a fizetés, rendelés és idősáv-foglalás maradjon kézi – vedd ki a pipát pl. az `update_payment_method_checkout`, `reserve_timeslot`, `repeat_order`, `cancel_order`, `submit_claim` mellől. Az asszisztens így is keres, kosárba tesz, és látja a rendeléseket, idősávokat és a pénztárt.

## Hálózat és biztonság
- Az add-on a **42783** porton figyel (SSE a `/sse` útvonalon, a hostra mappelve), a bejelentkező oldalt kizárólag a Home Assistant **ingress**-en át szolgálja ki.
- Az SSE végpontnak **nincs saját hitelesítése**: aki eléri a 42783-as portot, az használhatja a bejelentkezett Kifli-fiókodat. Ha csak az ugyanazon a gépen futó Home Assistant használja, az add-on *Hálózat* beállításaiban törölheted a host portot, és az MCP-integrációt a belső hostnévre irányíthatod: `http://<add-on hostnév>:42783/sse` (az add-on slugja, `_` helyett `-` jellel, pl. `xxxxxxxx-kifli-mcp-connector`).
- Jelszó nem tárolódik: az add-on egy OAuth access/refresh tokent tart a `/data/oauth/` alatt (600-as jogokkal), és azt küldi Bearer tokenként HTTPS-en.
- A `homeassistant_api: true` egyetlen dologra kell: sikeres bejelentkezés után újratölti az MCP-integrációt.

## Támogatott architektúrák
`amd64`, `aarch64`. (Az `armv7` / `armhf` eltávolítva — a Home Assistant 2025.12 óta nem támogatja.)

## Hibaelhárítás
- **Nincsenek toolok, az Assist azt mondja, a Kifli MCP nincs bejelentkezve:** nyisd meg a **Kifli MCP** oldalt az oldalsávban, és vidd végig a bejelentkezést (lásd *Bejelentkezés*). Addig a tool-lista szándékosan üres.
- **Bejelentkezés után a böngésző „nem lehet elérni a localhost:3334” hibát ír:** ez a normális utolsó lépés – másold ki a címet, és illeszd be a Kifli MCP oldalon.
- **„RHL-EMAIL/RHL-PASS header login is obsolete” a logban / `Timeout when listing tools` a Home Assistantban:** 1.x verzión vagy; frissíts 2.0-ra, és jelentkezz be OAuth-tal.
- **Nem jelennek meg toolok a Home Assistantban:** ellenőrizd, hogy az add-on fut, és az SSE URL pontosan `http://<ha-ip>:42783/sse`; töltsd újra az MCP integrációt.
- **Nézd a logot:** az indulási sor kiírja a feloldott `country` és `url` értéket, így ellenőrizheted, hogy a megfelelő végpontot használja.
- **Egyszerre eltűnik az összes MCP tool, és az LLM `tools.NN.custom.input_schema: JSON schema is invalid` hibát ad (Home Assistant 2026.9+):**
  Javítva az add-on **1.2.1**-es verziójában — frissíts és indítsd újra az add-ont.

  A Home Assistant a 2026.9-ben lecserélte a séma-konvertert (`voluptuous-openapi` → `probatio`). Az új konverter `from_openapi()` / `to_openapi()` köre a draft 2020-12-es **szám** alakú `exclusiveMinimum` / `exclusiveMaximum` kulcsot az elavult draft-04-es **boolean** alakra írja át:

  ```
  amit a shim küld:      {"exclusiveMinimum": 0, "type": "integer"}
  amit a HA csinál belőle: {"minimum": 0, "exclusiveMinimum": true, "type": "number"}
  ```

  A draft 2020-12 az `exclusiveMinimum`-tól *számot* vár, tehát a `true` érvénytelen. Az Anthropic API pedig egyetlen hibás séma miatt a **teljes toollistát** eldobja — ezért tűnik el *az összes* tool, nem csak az érintettek. Három tool hordozott szám alakú kizáró határt: `add_products_to_shopping_list`, `remove_products_from_shopping_list`, `delete_shopping_list`.

  A sémák végig érvényesek voltak; ez a konverter-regresszió megkerülése. A shim mostantól normalizálja a kizáró határokat, mielőtt kiengedi őket: `integer` típusnál pontos inkluzív megfelelőre (`exclusiveMinimum: 0` → `minimum: 1`), egyéb típusnál a határt megtartva elhagyja a kulcsot.
