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