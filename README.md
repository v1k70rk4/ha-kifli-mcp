# ha-kifli-mcp

Home Assistant add-on repository: **Kifli MCP Connector**.

Ez az add-on a Kifli/Rohlík MCP végpontot “áthidalja” egy, Home Assistantból könnyen fogyasztható **SSE (Server-Sent Events)** interfészre, és tartalmaz egy **schema shim** réteget is, ami a tool schema-kat a HA/OpenAI szigorúbb elvárásaihoz igazítja.

## Telepítés (Add-on repository hozzáadása)

### 1-kattintásos (My Home Assistant)
Nyisd meg ezt a linket, és add hozzá a repository-t a Home Assistant Add-on Store-hoz:

`https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fv1k70rk4%2Fha-kifli-mcp`

### Kézzel
1. Home Assistant: **Settings → Add-ons → Add-on Store**
2. Jobb felső menü (⋮) → **Repositories**
3. Add hozzá:
   - `https://github.com/v1k70rk4/ha-kifli-mcp`

Ezután az add-on megjelenik a Store-ban.

## Add-on
- Add-on mappa: [`kifli_mcp_connector/`](./kifli_mcp_connector)
- Dokumentáció: [`kifli_mcp_connector/README.md`](./kifli_mcp_connector/README.md)
- Changelog: [`kifli_mcp_connector/CHANGELOG.md`](./kifli_mcp_connector/CHANGELOG.md)

## Biztonsági megjegyzések
- Az add-on bejelentkezési adatokat (email/jelszó) kér a Kifli/Rohlík szolgáltatáshoz.
- A jelszó a Home Assistant add-on konfigurációjában tárolódik.
- Az add-on a működéshez **host network** módot használ (lásd add-on README).

## License
Válassz licencet (pl. MIT) és add hozzá a `LICENSE` fájlt a repóhoz.