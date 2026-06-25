# Kifli MCP Connector

**Kifli/Rohlík MCP → SSE bridge** Home Assistant környezethez, beépített **schema shim**-mel.

Az add-on célja, hogy a Kifli/Rohlík MCP tooljait egy Home Assistantból egyszerűen elérhető **SSE endpointon** tegye elérhetővé, miközben a tool input schema-kat “megszelídíti” a Home Assistant / OpenAI function tooling elvárásaihoz.

## Mit kapsz?
- MCP remote kliens a Kifli/Rohlik Group MCP felé (HU/CZ/AT/DE/RO)
- `mcp-proxy` SSE szerver a Home Assistant felé
- `mcp_schema_shim.py`: schema normalizálás (refs, unions, unsupported kulcsok, üres object properties fix)

## Telepítés
1. Add hozzá a repository-t:
   - `https://github.com/v1k70rk4/ha-kifli-mcp`
2. Add-on Store-ban telepítsd: **Kifli MCP Connector**
3. Konfiguráld (email/jelszó), majd indítsd el.

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
2. Nyisd meg a használt asszisztenst (pl. “OpenAI”)
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
A válaszokból szedd ki a kép hivatkozást, azokat a rendszer nem tudja megjeleníteni.```
