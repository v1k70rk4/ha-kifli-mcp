> 🇭🇺 **Magyar leírás a lap alján — [ugorj a magyar változatra](#magyar).**

# Rohlik Group (hu, cz, at, de, ro) MCP Connector

[![Build add-on](https://github.com/v1k70rk4/ha-kifli-mcp/actions/workflows/build.yaml/badge.svg)](https://github.com/v1k70rk4/ha-kifli-mcp/actions/workflows/build.yaml)
[![Lint add-on](https://github.com/v1k70rk4/ha-kifli-mcp/actions/workflows/lint-addon.yaml/badge.svg)](https://github.com/v1k70rk4/ha-kifli-mcp/actions/workflows/lint-addon.yaml)
[![Lint with Ruff](https://github.com/v1k70rk4/ha-kifli-mcp/actions/workflows/ruff.yaml/badge.svg)](https://github.com/v1k70rk4/ha-kifli-mcp/actions/workflows/ruff.yaml)
[![Test](https://github.com/v1k70rk4/ha-kifli-mcp/actions/workflows/test.yaml/badge.svg)](https://github.com/v1k70rk4/ha-kifli-mcp/actions/workflows/test.yaml)
[![CodeQL](https://github.com/v1k70rk4/ha-kifli-mcp/actions/workflows/codeql.yaml/badge.svg)](https://github.com/v1k70rk4/ha-kifli-mcp/actions/workflows/codeql.yaml)

Home Assistant add-on repository: **Rohlik Group (hu, cz, at, de, ro) MCP Connector**.

> ⚠️ Unofficial / community project. Not affiliated with, endorsed by, or operated by Rohlik Group.

This add-on bridges the Rohlik Group MCP endpoint (Kifli.hu, Rohlik.cz, Gurkerl.at, Knuspr.de, Sezamo.ro) to an **SSE (Server-Sent Events)** interface that Home Assistant can consume easily, and includes a **schema shim** layer that adapts the tool schemas to the stricter HA/OpenAI expectations.

## Installation (add the add-on repository)

### One-click (My Home Assistant)
Open this link and add the repository to the Home Assistant Add-on Store:

[![Add to Home Assistant](https://my.home-assistant.io/badges/supervisor_addon.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fv1k70rk4%2Fha-kifli-mcp)

### Manually
1. Home Assistant: **Settings → Add-ons → Add-on Store**
2. Top-right menu (⋮) → **Repositories**
3. Add:
   - `https://github.com/v1k70rk4/ha-kifli-mcp`

The add-on then appears in the Store.

## Add-on
- Add-on folder: [`kifli_mcp_connector/`](./kifli_mcp_connector)
- Documentation: [`kifli_mcp_connector/DOCS.md`](./kifli_mcp_connector/DOCS.md)
- Changelog: [`kifli_mcp_connector/CHANGELOG.md`](./kifli_mcp_connector/CHANGELOG.md)

## Supported countries
| `country` | Brand | MCP endpoint |
|-----------|-------|--------------|
| `hu` | Kifli.hu (Hungary) | `https://mcp.kifli.hu/mcp` |
| `cz` | Rohlik.cz (Czechia) | `https://mcp.rohlik.cz/mcp` |
| `at` | Gurkerl.at (Austria) | `https://mcp.gurkerl.at/mcp` |
| `de` | Knuspr.de (Germany) | `https://mcp.knuspr.de/mcp` |
| `ro` | Sezamo.ro (Romania) | `https://mcp.sezamo.ro/mcp` |

(Slovakia is not operated by Rohlik Group. Use the add-on's `mcp_url` option for any unlisted endpoint.)

## Security notes
- No password is stored: you sign in with OAuth on the add-on's **Kifli MCP** page (Home Assistant ingress), and the add-on keeps only an access/refresh token under `/data/oauth/`.
- No host network: the SSE endpoint is published on port **42783**, the sign-in page only through ingress.
- The SSE endpoint has **no authentication of its own** (anyone who can reach port 42783 can use your signed-in account) and only answers requests addressed to a host name it knows: the Home Assistant host's IP addresses and names, the add-on's internal host name, and the ones in `allowed_hosts`.
- Details: [*Networking & security* in DOCS.md](./kifli_mcp_connector/DOCS.md#networking--security).

---

<a name="magyar"></a>

# 🇭🇺 Magyar — Rohlik Group (hu, cz, at, de, ro) MCP Connector

Home Assistant add-on repository: **Rohlik Group (hu, cz, at, de, ro) MCP Connector**.

> ⚠️ Nem hivatalos / közösségi projekt. Nem áll kapcsolatban a Rohlik Grouppal, és nem a Rohlik Group üzemelteti.

Ez az add-on a Rohlik Group MCP végpontját (Kifli.hu, Rohlik.cz, Gurkerl.at, Knuspr.de, Sezamo.ro) „áthidalja" egy, Home Assistantból könnyen fogyasztható **SSE (Server-Sent Events)** interfészre, és tartalmaz egy **schema shim** réteget is, ami a tool schema-kat a HA/OpenAI szigorúbb elvárásaihoz igazítja.

## Telepítés (Add-on repository hozzáadása)

### 1-kattintásos (My Home Assistant)
Nyisd meg ezt a linket, és add hozzá a repository-t a Home Assistant Add-on Store-hoz:

[![Add to Home Assistant](https://my.home-assistant.io/badges/supervisor_addon.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fv1k70rk4%2Fha-kifli-mcp)

### Kézzel
1. Home Assistant: **Settings → Add-ons → Add-on Store**
2. Jobb felső menü (⋮) → **Repositories**
3. Add hozzá:
   - `https://github.com/v1k70rk4/ha-kifli-mcp`

Ezután az add-on megjelenik a Store-ban.

## Add-on
- Add-on mappa: [`kifli_mcp_connector/`](./kifli_mcp_connector)
- Dokumentáció: [`kifli_mcp_connector/DOCS.md`](./kifli_mcp_connector/DOCS.md)
- Változásnapló: [`kifli_mcp_connector/CHANGELOG.md`](./kifli_mcp_connector/CHANGELOG.md)

## Támogatott országok
| `country` | Márka | MCP végpont |
|-----------|-------|-------------|
| `hu` | Kifli.hu (Magyarország) | `https://mcp.kifli.hu/mcp` |
| `cz` | Rohlik.cz (Csehország) | `https://mcp.rohlik.cz/mcp` |
| `at` | Gurkerl.at (Ausztria) | `https://mcp.gurkerl.at/mcp` |
| `de` | Knuspr.de (Németország) | `https://mcp.knuspr.de/mcp` |
| `ro` | Sezamo.ro (Románia) | `https://mcp.sezamo.ro/mcp` |

(Szlovákiában a Rohlik Group nem üzemeltet szolgáltatást. Nem listázott végponthoz használd az add-on `mcp_url` opcióját.)

## Biztonsági megjegyzések
- Jelszó nem tárolódik: a bejelentkezés OAuth-tal történik az add-on **Kifli MCP** oldalán (Home Assistant ingress), az add-on csak egy access/refresh tokent tart a `/data/oauth/` alatt.
- Nincs host network: az SSE végpont a **42783**-as porton érhető el, a bejelentkező oldal csak ingressen át.
- Az SSE végpontnak **nincs saját hitelesítése** (aki eléri a 42783-as portot, használhatja a bejelentkezett fiókodat), és csak az általa ismert hostnévre címzett kérésekre válaszol: a Home Assistant gép IP-címeire és neveire, az add-on belső hostnevére és az `allowed_hosts`-ban megadottakra.
- Részletek: [*Hálózat és biztonság* a DOCS.md-ben](./kifli_mcp_connector/DOCS.md#hálózat-és-biztonság).
