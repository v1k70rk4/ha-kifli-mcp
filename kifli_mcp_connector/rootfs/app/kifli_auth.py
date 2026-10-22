"""OAuth bejelentkezés a Rohlik Group MCP-hez + a hozzá tartozó ingress oldal.

A Rohlik Group 2026 októberében megszüntette az ``rhl-email`` / ``rhl-pass``
fejléces bejelentkezést; az MCP végpont azóta csak OAuth 2.1 (PKCE) tokent
fogad el. Az identity szerver kizárólag ``http://localhost:...`` visszahívási
címet enged dinamikusan regisztrált kliensnek, az add-on viszont a HA gépen,
böngésző nélkül fut – ezért a visszahívást nem tudjuk fogadni.

A megoldás: a bejelentkezés után a böngésző egy ``http://localhost:3334/...?code=...``
címre irányít (ami a felhasználó gépén "nem tölthető be"), ezt a címet a
felhasználó bemásolja az add-on ingress oldalán, mi pedig kinyerjük belőle a
kódot és a state-et. Innen az SDK ``OAuthClientProvider``-e viszi tovább
(token csere, tárolás, automatikus frissítés).

Minden napló a STDERR-re megy: a STDOUT az MCP stdio csatorna.
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import json
import logging
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route

log = logging.getLogger("kifli.auth")

# A dinamikus kliensregisztráció csak localhost redirectet fogad el; a port
# tetszőleges, a 3334 az mcp-remote öröksége, így a régi leírások is stimmelnek.
REDIRECT_URI = "http://localhost:3334/oauth/callback"
SCOPE = "openid email roles offline_access"
CLIENT_NAME = "Home Assistant – Kifli MCP Connector"


class FileTokenStorage(TokenStorage):
    """Tokenek és kliensadatok JSON-ban, a HA add-on tartós /data könyvtárában."""

    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)
        self._tokens = self.dir / "tokens.json"
        self._client = self.dir / "client.json"

    def _read(self, path: Path) -> dict | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _write(self, path: Path, data: dict) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        with contextlib.suppress(OSError):
            tmp.chmod(0o600)
        tmp.replace(path)

    async def get_tokens(self) -> OAuthToken | None:
        data = self._read(self._tokens)
        return OAuthToken.model_validate(data) if data else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._write(self._tokens, tokens.model_dump(exclude_none=True))

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        data = self._read(self._client)
        return OAuthClientInformationFull.model_validate(data) if data else None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._write(self._client, client_info.model_dump(exclude_none=True, mode="json"))

    def has_tokens(self) -> bool:
        return self._tokens.exists()

    def clear(self) -> None:
        for p in (self._tokens, self._client):
            with contextlib.suppress(FileNotFoundError):
                p.unlink()


class KifliOAuthProvider(OAuthClientProvider):
    """Az SDK a scope-ot az MCP spec szerint a szerver által hirdetett listára
    (`openid email roles`) cseréli, ami kihagyja az ``offline_access``-t – az
    pedig kell ahhoz, hogy frissítő tokent kapjunk, és ne kelljen naponta újra
    bejelentkezni. A regisztrált kliens scope-ja tartalmazza, az identity
    szerver elfogadja, ezért az engedélykérés előtt visszatesszük."""

    async def _perform_authorization_code_grant(self) -> tuple[str, str]:
        current = (self.context.client_metadata.scope or "").split()
        for extra in ("offline_access",):
            if extra not in current:
                current.append(extra)
        self.context.client_metadata.scope = " ".join(current)
        return await super()._perform_authorization_code_grant()


class AuthManager:
    """Az OAuth folyamat állapota + a provider, amit az upstream kapcsolat használ."""

    def __init__(self, mcp_url: str, data_dir: Path) -> None:
        self.mcp_url = mcp_url
        self.storage = FileTokenStorage(data_dir / "oauth")
        self.auth_url: str | None = None  # amire a felhasználónak kattintania kell
        self.status = "init"  # init | needs_login | waiting_code | exchanging | ok | error
        self.error: str | None = None
        self.logged_in = asyncio.Event()
        self._code: asyncio.Future[tuple[str, str | None]] | None = None
        self.provider = KifliOAuthProvider(
            server_url=mcp_url,
            client_metadata=OAuthClientMetadata(
                client_name=CLIENT_NAME,
                redirect_uris=[REDIRECT_URI],
                grant_types=["authorization_code", "refresh_token"],
                response_types=["code"],
                token_endpoint_auth_method="none",
                scope=SCOPE,
            ),
            storage=self.storage,
            redirect_handler=self._on_redirect,
            callback_handler=self._wait_for_code,
            timeout=24 * 3600,
        )

    # --- az SDK hívja ---------------------------------------------------------
    async def _on_redirect(self, url: str) -> None:
        self.auth_url = url
        self.status = "waiting_code"
        loop = asyncio.get_running_loop()
        self._code = loop.create_future()
        log.warning("BEJELENTKEZÉS SZÜKSÉGES. Nyisd meg az add-on oldalát a HA oldalsávban, vagy ezt a címet:")
        log.warning("  %s", url)
        log.warning("Bejelentkezés után a böngésző egy localhost:3334/... címre irányít – azt másold be az add-on oldalán.")

    async def _wait_for_code(self) -> tuple[str, str | None]:
        assert self._code is not None
        code, state = await self._code
        self.status = "exchanging"
        return code, state

    # --- az ingress oldal hívja -----------------------------------------------
    def submit_callback_url(self, pasted: str) -> str | None:
        """A bemásolt átirányítási URL feldolgozása. Hibaüzenettel tér vissza, ha rossz."""
        pasted = pasted.strip()
        if not pasted:
            return "Üres mező. / Empty field."
        try:
            parts = urlsplit(pasted if "://" in pasted else "http://x/?" + pasted.lstrip("?"))
            q = parse_qs(parts.query)
        except ValueError:
            return "Nem tudom értelmezni a címet. / Could not parse the URL."
        if "error" in q:
            return f"A Kifli hibát adott vissza: {q['error'][0]} {q.get('error_description', [''])[0]}"
        code = q.get("code", [None])[0]
        state = q.get("state", [None])[0]
        if not code:
            return "A címben nincs 'code' paraméter. / No 'code' parameter in the URL."
        if self._code is None or self._code.done():
            return (
                "Most nincs folyamatban bejelentkezés – indíts újat a gombbal. / "
                "No login in progress – start a new one with the button."
            )
        self._code.set_result((code, state))
        return None

    async def logout(self) -> None:
        self.storage.clear()
        self.logged_in.clear()
        self.status = "needs_login"
        self.auth_url = None

    # --- bejelentkezés kikényszerítése ----------------------------------------
    async def ensure_logged_in(self) -> None:
        """Egy hitelesített kérés az MCP végpontra: ha nincs érvényes token, az SDK
        lefuttatja a teljes OAuth folyamatot (felfedezés, regisztráció, redirect,
        kód bevárása, token csere). Sikeres végén tokenünk van."""
        self.error = None
        if not self.storage.has_tokens():
            self.status = "needs_login"
        body = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "kifli-schema-shim", "version": "auth-check"},
            },
        }
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        async with httpx.AsyncClient(auth=self.provider, timeout=httpx.Timeout(60.0)) as client:
            resp = await client.post(self.mcp_url, json=body, headers=headers)
        if resp.status_code == 401:
            raise RuntimeError(f"A bejelentkezés után is 401: {resp.text[:200]}")
        resp.raise_for_status()
        self.status = "ok"
        self.auth_url = None
        self.logged_in.set()
        log.info("Kifli OAuth bejelentkezés rendben, token elmentve.")


# --- Home Assistant: az MCP integráció újratöltése bejelentkezés után ------------

async def reload_ha_mcp_entry(local_port: int) -> str:
    """A Supervisor proxyn át megkeressük a HA `mcp` config entry-t, ami erre az
    add-onra mutat, és újratöltjük – így a toolok azonnal megjelennek, nem 30 perc
    múlva. Ehhez a config.yaml-ban `homeassistant_api: true` kell."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return "nincs SUPERVISOR_TOKEN"
    base = "http://supervisor/core/api"
    h = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{base}/config/config_entries/entry", params={"domain": "mcp"}, headers=h)
            r.raise_for_status()
            entries = r.json()
            done = []
            for e in entries:
                title = str(e.get("title", ""))
                # a HA az URL-ből képez címet; a mi portunk benne van, vagy csak egy MCP entry van
                if f":{local_port}" in title or len(entries) == 1:
                    rr = await c.post(f"{base}/config/config_entries/entry/{e['entry_id']}/reload", headers=h)
                    done.append(f"{title} → {rr.status_code}")
            return "; ".join(done) if done else "nem találtam ide mutató MCP entry-t"
    except Exception as ex:  # noqa: BLE001 – csak kényelmi funkció, soha ne döntse be a shimet
        return f"hiba: {ex}"


# --- Ingress oldal -------------------------------------------------------------

PAGE = """<!doctype html><html lang="hu"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kifli MCP</title>
<style>
 body{{font-family:system-ui,sans-serif;max-width:720px;margin:2rem auto;padding:0 1rem;color:#222;background:#fafafa}}
 .card{{background:#fff;border-radius:12px;padding:1.2rem 1.5rem;box-shadow:0 1px 4px #0002;margin-bottom:1.2rem}}
 .ok{{color:#2e7d32}} .warn{{color:#e65100}} .err{{color:#c62828}}
 input[type=text]{{width:100%;padding:.6rem;font-size:1rem;border:1px solid #bbb;border-radius:8px;box-sizing:border-box}}
 button,a.btn{{display:inline-block;padding:.6rem 1.2rem;border:0;border-radius:8px;background:#1e88e5;color:#fff;font-size:1rem;cursor:pointer;text-decoration:none;margin-top:.6rem}}
 button.sec{{background:#777}} code{{background:#eee;padding:.1rem .3rem;border-radius:4px}} small{{color:#666}}
 ol li{{margin:.4rem 0}}
 table{{width:100%;border-collapse:collapse}} td{{padding:.35rem .3rem;border-top:1px solid #eee;vertical-align:top}}
 td.n{{white-space:nowrap}} .new{{background:#fff3e0;color:#e65100;border-radius:4px;padding:0 .3rem;font-size:.8rem}}
 .gone{{color:#999;text-decoration:line-through}}
 .toast{{position:fixed;left:50%;bottom:1.2rem;transform:translateX(-50%);background:#2e7d32;color:#fff;padding:.7rem 1.2rem;border-radius:10px;box-shadow:0 2px 8px #0004;max-width:90%;animation:fade 6s forwards}}
 .toast.err{{background:#c62828}} @keyframes fade{{0%,80%{{opacity:1}}100%{{opacity:0;visibility:hidden}}}}
</style></head><body>
<h1>🛒 Kifli / Rohlik MCP</h1>
<div class="card"><b>Állapot / Status:</b> {status_html}{error_html}</div>
{body}
{tools}
{toast}
<p><small>Végpont / endpoint: <code>{mcp_url}</code> · SSE a Home Assistantnak: <code>http://&lt;ha-ip&gt;:{port}/sse</code></small></p>
</body></html>"""

LOGIN_BODY = """
<div class="card">
<h3>1️⃣ Bejelentkezés a Kifli-fiókoddal</h3>
<p>Kattints a gombra, jelentkezz be az <b>identity.kifli.hu</b> oldalon (ugyanaz a fiók, mint a webshopban).</p>
{auth_button}
<h3>2️⃣ Másold be, ahova átirányított</h3>
<p>Bejelentkezés után a böngésző egy <code>http://localhost:3334/oauth/callback?code=…</code> címre ugrik, és azt írja,
hogy <i>nem lehet elérni az oldalt</i>. <b>Ez így normális.</b> Másold ki a teljes címet a címsorból, és illeszd be ide:</p>
<form method="post" action="callback">
 <input type="text" name="url" placeholder="http://localhost:3334/oauth/callback?code=…&state=…" autocomplete="off">
 <button type="submit">Beküldés / Submit</button>
</form>
<p><small><b>EN:</b> Click the button, sign in with your Kifli/Rohlik account, then paste the <code>localhost:3334/…</code>
URL your browser was redirected to (the "can't reach this page" one) into the box above.</small></p>
</div>"""

OK_BODY = """
<div class="card">
<p class="ok">✅ Bejelentkezve. A Home Assistant MCP-integrációja látja a toolokat.<br>
<small>Logged in – the Home Assistant MCP integration can see the tools.</small></p>
<p><small>Ha a toolok még nem látszanak az Assistban: Beállítások → Eszközök és szolgáltatások → MCP → ⋮ → Újratöltés.
A token magától frissül; ha mégis lejárna, ez az oldal újra a bejelentkezést mutatja.</small></p>
<form method="post" action="logout"><button class="sec" type="submit">Kijelentkezés / Log out</button></form>
</div>"""

STATUS_TEXT = {
    "init": ("warn", "indulás… / starting…"),
    "needs_login": ("warn", "bejelentkezés szükséges / login required"),
    "waiting_code": ("warn", "várom a bemásolt címet / waiting for the pasted URL"),
    "exchanging": ("warn", "token csere… / exchanging token…"),
    "ok": ("ok", "bejelentkezve / logged in"),
    "error": ("err", "hiba / error"),
}


def render_tools(settings) -> str:
    """A funkciók (MCP eszközök) ki/be kapcsoló kártyája."""
    if settings is None or not settings.tools:
        return ""
    rows = []
    for name, e in settings.listing():
        missing = e.get("missing")
        badge = ' <span class="new">új</span>' if e.get("is_new") else ""
        cls = ' class="gone"' if missing else ""
        chk = " checked" if e.get("enabled") else ""
        dis = " disabled" if missing else ""
        desc = html.escape(" ".join(str(e.get("description", "")).split())[:220])
        rows.append(
            f'<tr><td><input type="checkbox" name="tool" value="{html.escape(name)}"{chk}{dis}></td>'
            f'<td class="n"><code{cls}>{html.escape(name)}</code>{badge}</td><td><small>{desc}</small></td></tr>'
        )
    on = sum(1 for _, e in settings.listing() if e.get("enabled") and not e.get("missing"))
    total = sum(1 for _, e in settings.listing() if not e.get("missing"))
    return f"""<div class="card"><h3>⚙️ Funkciók / Tools ({on}/{total} bekapcsolva)</h3>
<p><small>Csak a bepipált funkciókat látja a Home Assistant (Assist, automatizmusok); a kikapcsoltat
akkor sem lehet meghívni, ha valaki közvetlenül a portra csatlakozik. Az újonnan megjelenő funkciók
{'bekapcsolva' if settings.new_tools_enabled else '<b>kikapcsolva</b>'} érkeznek, és értesítés jön róluk.
<br>Only checked tools are exposed to Home Assistant; unchecked ones are also refused on direct calls.</small></p>
<form method="post" action="tools">
<input type="hidden" name="rev" value="{settings.rev}">
<p><button type="button" class="sec" onclick="document.querySelectorAll('input[name=tool]:not(:disabled)').forEach(c=>c.checked=true)">Mind be</button>
<button type="button" class="sec" onclick="document.querySelectorAll('input[name=tool]').forEach(c=>c.checked=false)">Mind ki</button></p>
<table>{''.join(rows)}</table>
<button type="submit">Mentés / Save</button></form></div>"""


def build_app(auth: AuthManager, port: int, on_login_ok, settings=None, on_tools_saved=None) -> Starlette:
    def render(message: str | None = None, msg_class: str = "err") -> HTMLResponse:
        cls, text = STATUS_TEXT.get(auth.status, ("warn", auth.status))
        status_html = f'<span class="{cls}">{html.escape(text)}</span>'
        err = auth.error or message
        error_html = f'<p class="{msg_class}">{html.escape(err)}</p>' if err else ""
        if auth.status == "ok":
            body = OK_BODY
        else:
            if auth.auth_url:
                btn = f'<a class="btn" href="{html.escape(auth.auth_url)}" target="_blank" rel="noopener">🔐 Bejelentkezés / Sign in</a>'
            else:
                btn = '<form method="post" action="start"><button type="submit">🔐 Bejelentkezés indítása / Start login</button></form>'
            body = LOGIN_BODY.format(auth_button=btn)
        return HTMLResponse(PAGE.format(status_html=status_html, error_html=error_html, body=body,
                                        tools=render_tools(settings),
                                        toast=(f'<div class="toast {msg_class}">{html.escape(message)}</div>' if message else ""),
                                        mcp_url=html.escape(auth.mcp_url), port=port))

    async def index(_: Request):
        return render()

    async def callback(request: Request):
        form = await request.form()
        err = auth.submit_callback_url(str(form.get("url", "")))
        if err:
            return render(err)
        # megvárjuk a token cserét (pár másodperc), hogy a válasz már a végeredményt mutassa
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(auth.logged_in.wait(), timeout=25)
        if auth.status == "ok":
            note = await on_login_ok()
            return render(f"Siker! HA MCP integráció újratöltve: {note}", "ok")
        return render()

    async def start(_: Request):
        if auth.status not in ("waiting_code", "exchanging"):
            asyncio.get_running_loop().create_task(_safe_login(auth))
            # adunk egy pillanatot a felfedezésnek + regisztrációnak, hogy legyen URL
            for _i in range(40):
                if auth.auth_url:
                    break
                await asyncio.sleep(0.25)
        return RedirectResponse(url=".", status_code=303)

    async def tools(request: Request):
        if settings is None:
            return RedirectResponse(url=".", status_code=303)
        if request.headers.get("content-type", "").startswith("application/json"):
            # gépi beállítás (pl. Supervisor proxy): {"enabled": ["tool_a", ...]}
            data = await request.json()
            names = data.get("enabled") if isinstance(data, dict) else None
            if not isinstance(names, list):
                return render('JSON esetén {"enabled": [...]} kell. / Expected {"enabled": [...]}.')
            settings.set_enabled({str(v) for v in names})
        else:
            form = await request.form()
            # elavult oldalról (pl. másik fülön közben módosítottak) ne írjuk vissza a régi állapotot
            if str(form.get("rev", "")) != str(settings.rev):
                return render(
                    "Az oldal elavult, közben módosult a beállítás – frissítsd az oldalt (F5), és mentsd újra. / "
                    "This page is out of date – reload it and save again."
                )
            settings.set_enabled({str(v) for v in form.getlist("tool")})
        note = await on_tools_saved() if on_tools_saved else ""
        return render(f"Mentve. HA MCP integráció újratöltve: {note}", "ok")

    async def logout(_: Request):
        await auth.logout()
        return RedirectResponse(url=".", status_code=303)

    async def status(_: Request):
        return JSONResponse({"status": auth.status, "error": auth.error, "logged_in": auth.logged_in.is_set()})

    return Starlette(routes=[
        Route("/", index),
        Route("/callback", callback, methods=["POST"]),
        Route("/start", start, methods=["POST"]),
        Route("/logout", logout, methods=["POST"]),
        Route("/tools", tools, methods=["POST"]),
        Route("/status", status),
    ])


async def _safe_login(auth: AuthManager) -> None:
    try:
        await auth.ensure_logged_in()
    except Exception as ex:  # noqa: BLE001
        auth.status = "error"
        auth.error = f"{type(ex).__name__}: {ex}"
        log.error("Kifli OAuth bejelentkezés sikertelen: %s", auth.error)


def setup_logging() -> None:
    """Minden napló STDERR-re – a STDOUT az MCP stdio csatorna."""
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
