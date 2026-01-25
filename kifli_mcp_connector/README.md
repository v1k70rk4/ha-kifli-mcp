# Kifli MCP Connector

**Kifli/Rohlík MCP → SSE bridge** Home Assistant környezethez, beépített **schema shim**-mel.

Az add-on célja, hogy a Kifli/Rohlík MCP tooljait egy Home Assistantból egyszerűen elérhető **SSE endpointon** tegye elérhetővé, miközben a tool input schema-kat “megszelídíti” a Home Assistant / OpenAI function tooling elvárásaihoz.

## Mit kapsz?
- MCP remote kliens a Kifli MCP felé
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
| `email` | string | `""` | Kifli/Rohlík login email |
| `password` | password | `""` | Kifli/Rohlík login jelszó |

### Példa
```yaml
port: 42783
email: "user@example.com"
password: "********"
```

Az SSE endpoint (alapesetben): `http://<home_assistant_ip>:42783/`

### MCP szerver felvétele (Eszközök és szolgáltatások)
1. Home Assistant: **Beállítások → Eszközök és szolgáltatások**
2. **Integráció hozzáadása**
3. Keresd meg: **Model Context Protocol (MCP)**
4. Add meg az MCP SSE URL-t:
   - `http://<home_assistant_ip>:42783/`
5. Mentsd el, várd meg míg az integráció felveszi a toolokat.

### MCP hozzáadása az Assisthoz
1. Home Assistant: **Beállítások → Hangsegédek (Assist)**
2. Nyisd meg a használt asszisztenst (pl. “OpenAI”)
3. A **Tools / Eszközök / Toolok** résznél engedélyezd / add hozzá az **MCP** integrációt
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
