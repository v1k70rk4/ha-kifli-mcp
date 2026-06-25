> 🇭🇺 **Magyar leírás a lap alján — [ugorj a magyar változatra](#magyar).**

# Rohlik Group (hu, cz, at, de, ro) MCP Connector

**Rohlik Group MCP → SSE bridge** for Home Assistant, with a built-in **schema shim**.

> ⚠️ **Unofficial / community add-on.** Not affiliated with, endorsed by, or operated by Rohlik Group. You use your own account credentials at your own risk.

This add-on exposes the Rohlik Group MCP tools (Kifli.hu, Rohlik.cz, Gurkerl.at, Knuspr.de, Sezamo.ro) on an **SSE endpoint** that Home Assistant can consume directly, while a **schema shim** normalizes the tool input schemas to satisfy the stricter Home Assistant / OpenAI function-tooling expectations.

## What you get
- MCP remote client to the Kifli / Rohlik Group MCP (HU/CZ/AT/DE/RO)
- `mcp-proxy` SSE server towards Home Assistant
- `mcp_schema_shim.py`: schema normalization (refs, unions, unsupported keys, empty-object-properties fix)

## How it works
```
Home Assistant (MCP client)
        │  SSE  →  http://<ha-ip>:42783/sse
        ▼
   mcp-proxy ──stdio──► mcp_schema_shim.py ──► mcp-remote ──HTTPS──► Rohlik Group MCP
                                                (rhl-email / rhl-pass headers)
```

## Prerequisites
- A working **Rohlik Group account** in your country (e.g. Kifli.hu for `hu`, Rohlik.cz for `cz`, …).
- The email/password you use to log in to that country's web shop.

## Installation
1. Add the repository:
   - `https://github.com/v1k70rk4/ha-kifli-mcp`
2. Install from the Add-on Store: **Rohlik Group (hu, cz, at, de, ro) MCP Connector**
3. Configure (country + email/password), then start it.

## Configuration

### Options
| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `port` | int | `42783` | SSE server port |
| `country` | list | `hu` | Rohlik Group country: `hu`, `cz`, `at`, `de`, `ro` (see below) |
| `email` | string | `""` | Login email for the selected country's service |
| `password` | password | `""` | Login password for the selected country's service |
| `mcp_url` | string | `""` | (Optional) Custom MCP endpoint; overrides the `country`-based URL |

### Example
```yaml
port: 42783
country: "hu"
email: "user@example.com"
password: "********"
```

### Supported countries (Rohlik Group)
The `country` option points to that country's MCP endpoint. The email/password you provide must belong to **an account of that country's service** (the auth headers are country-agnostic: `rhl-email` / `rhl-pass`).

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

## Networking & security
- The add-on runs in **host network** mode and listens on port **42783** (SSE at `/sse`).
- Your email/password are stored in the Home Assistant add-on configuration and sent to the selected MCP endpoint as `rhl-email` / `rhl-pass` headers over HTTPS.
- `mcp-remote` auth/cache is persisted under `/data/.mcp-auth`.

## Supported architectures
`amd64`, `aarch64`. (`armv7` / `armhf` were removed — unsupported by Home Assistant since 2025.12.)

## Troubleshooting
- **401 / authentication error:** wrong email/password, or the credentials don't match the selected `country`. Make sure the account belongs to that country's service.
- **No tools appear in Home Assistant:** confirm the add-on is running and the SSE URL is exactly `http://<ha-ip>:42783/sse`; reload the MCP integration.
- **Check the logs:** the startup line logs the resolved `country` and `url`, so you can verify the correct endpoint is being used.

---

<a name="magyar"></a>

# 🇭🇺 Magyar — Rohlik Group (hu, cz, at, de, ro) MCP Connector

**Rohlik Group MCP → SSE bridge** Home Assistant környezethez, beépített **schema shim**-mel.

> ⚠️ **Nem hivatalos / közösségi add-on.** Nem áll kapcsolatban a Rohlik Grouppal, és nem a Rohlik Group üzemelteti. A saját fiókod adatait saját felelősségre használod.

Az add-on célja, hogy a Rohlik Group MCP tooljait (Kifli.hu, Rohlik.cz, Gurkerl.at, Knuspr.de, Sezamo.ro) egy Home Assistantból egyszerűen elérhető **SSE endpointon** tegye elérhetővé, miközben a tool input schema-kat „megszelídíti” a Home Assistant / OpenAI function tooling elvárásaihoz.

## Mit kapsz?
- MCP remote kliens a Kifli / Rohlik Group MCP felé (HU/CZ/AT/DE/RO)
- `mcp-proxy` SSE szerver a Home Assistant felé
- `mcp_schema_shim.py`: schema normalizálás (refs, unions, unsupported kulcsok, üres object properties fix)

## Hogyan működik?
```
Home Assistant (MCP kliens)
        │  SSE  →  http://<ha-ip>:42783/sse
        ▼
   mcp-proxy ──stdio──► mcp_schema_shim.py ──► mcp-remote ──HTTPS──► Rohlik Group MCP
                                                (rhl-email / rhl-pass fejlécek)
```

## Előfeltételek
- Működő **Rohlik Group fiók** a saját országodban (pl. `hu`-hoz Kifli.hu, `cz`-hez Rohlik.cz, …).
- Az adott ország webshopjába belépő email/jelszó.

## Telepítés
1. Add hozzá a repository-t:
   - `https://github.com/v1k70rk4/ha-kifli-mcp`
2. Add-on Store-ban telepítsd: **Rohlik Group (hu, cz, at, de, ro) MCP Connector**
3. Konfiguráld (ország + email/jelszó), majd indítsd el.

## Konfiguráció

### Opciók
| Kulcs | Típus | Alap | Leírás |
|------|------|------|--------|
| `port` | int | `42783` | SSE szerver port |
| `country` | list | `hu` | Rohlik Group ország: `hu`, `cz`, `at`, `de`, `ro` (lásd lentebb) |
| `email` | string | `""` | A kiválasztott ország szolgáltatásához tartozó login email |
| `password` | password | `""` | A kiválasztott ország szolgáltatásához tartozó jelszó |
| `mcp_url` | string | `""` | (Opcionális) Egyedi MCP végpont; ha kitöltöd, felülírja a `country` szerinti URL-t |

### Példa
```yaml
port: 42783
country: "hu"
email: "user@example.com"
password: "********"
```

### Támogatott országok (Rohlik Group)
A `country` opció a megfelelő ország MCP végpontjára mutat. A megadott email/jelszó **az adott ország szolgáltatásához tartozó fiók** adata (a hitelesítő fejlécek ország-függetlenek: `rhl-email` / `rhl-pass`).

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

## Hálózat és biztonság
- Az add-on **host network** módban fut, és a **42783** porton figyel (SSE a `/sse` útvonalon).
- Az email/jelszó a Home Assistant add-on konfigurációjában tárolódik, és a kiválasztott MCP végpontra `rhl-email` / `rhl-pass` fejlécként, HTTPS-en megy.
- A `mcp-remote` auth/cache a `/data/.mcp-auth` alatt tárolódik tartósan.

## Támogatott architektúrák
`amd64`, `aarch64`. (Az `armv7` / `armhf` eltávolítva — a Home Assistant 2025.12 óta nem támogatja.)

## Hibaelhárítás
- **401 / hitelesítési hiba:** rossz email/jelszó, vagy az adatok nem a kiválasztott `country`-hoz tartoznak. Győződj meg róla, hogy a fiók az adott ország szolgáltatásához tartozik.
- **Nem jelennek meg toolok a Home Assistantban:** ellenőrizd, hogy az add-on fut, és az SSE URL pontosan `http://<ha-ip>:42783/sse`; töltsd újra az MCP integrációt.
- **Nézd a logot:** az indulási sor kiírja a feloldott `country` és `url` értéket, így ellenőrizheted, hogy a megfelelő végpontot használja.
