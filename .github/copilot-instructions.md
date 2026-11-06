# Copilot code review instructions

This repository is a Home Assistant add-on (`kifli_mcp_connector/`) that connects the Rohlik Group MCP servers (kifli.hu, rohlik.cz, gurkerl.at, knuspr.de, sezamo.ro) to Home Assistant's MCP integration. It signs in with OAuth, rewrites the upstream tool schemas into a form Home Assistant accepts (`mcp_schema_shim.py`) and serves them over SSE. The sign-in and tool settings page is served through Home Assistant ingress.

## How to review

- Start review comments with a short, one-sentence summary of the suggested fix.
- Do not comment on code style, formatting or linting issues; Ruff runs in CI.
- Flag comments that over-explain straightforward code, narrate the obvious, or read like AI commentary (multi-sentence justifications for a single line).
- Comments should explain why (a non-obvious constraint, surprising behaviour, a workaround), never what the next line does. Do not accept comments that justify a change by describing what the code looked like before.
- New code comments are in English. Older comments, log messages and the Hungarian halves of the docs are in Hungarian; do not ask to translate them.
- There is no PR template; do not ask for one.

## Dependencies

- Python dependencies are pinned in one place only: `kifli_mcp_connector/requirements.txt`. The Dockerfile and `tests/requirements.txt` install from it and must not pin versions themselves (`tests/test_addon_config.py` checks this). Flag a version pinned anywhere else.
- A pull request with a dependency version bump should only contain changes required for the version bump. If it includes other changes, request that they are removed from the PR.
- `KifliOAuthProvider` in `kifli_auth.py` overrides private methods of the MCP SDK's `OAuthClientProvider` (`_initialize`, `_perform_authorization_code_grant`). When `mcp` is bumped, check that these still exist and keep their signatures; a renamed method silently disables the override (no `offline_access`, signed out after every restart).

## Releases

A pull request that changes the add-on's behaviour for users must, in the same PR:

- bump `version` in `kifli_mcp_connector/config.yaml`;
- set `SERVER_VERSION` in `mcp_schema_shim.py` to the same version;
- add a `## <version> — YYYY-MM-DD` entry to `kifli_mcp_connector/CHANGELOG.md` in both the English part and the Hungarian part (below `<a name="magyar"></a>`).

Changes to tests, CI or repository docs only do not need a release. User-facing documentation (`README.md`, `kifli_mcp_connector/DOCS.md`, `kifli_mcp_connector/README.md`) is bilingual: a change to the English part needs the matching change in the Hungarian part, and the other way round.

## Add-on specifics

- The image must build on both `amd64` and `aarch64`. Without a `build.yaml` the Supervisor passes only `BUILD_ARCH`, so the Dockerfile derives the base image from it; flag a hard-coded `BUILD_FROM` or an architecture-specific base image (this broke aarch64 in 2.0.0, see #1).
- Every option in `config.yaml` needs a matching `schema` entry. Old options stay in the schema (as optional) so existing installations still pass validation; do not ask to remove them.
- Adding a country touches the `country` schema in `config.yaml`, the URL mapping in `rootfs/etc/services.d/kifli-mcp/run`, `EXPECTED_COUNTRY_URLS` in `tests/test_addon_config.py` and the country tables in the docs.
- The schema shim must never loosen a tool's constraints: a rewritten schema may only accept values the original accepted (bounds, `required`, `enum`, `allOf` parts). Flag any rewrite that drops or widens a limit.
- The add-on's state lives under `/data` (`/data/oauth/` for tokens, mode 600). Never log tokens, authorization codes or the contents of these files.
- The SSE endpoint (port 42783) has no authentication of its own, by design and documented in `DOCS.md`. Do not ask to add one in unrelated PRs, but flag changes that expose the add-on further (new ports, host network, the ingress page reachable without ingress).
- Calls to Home Assistant (notifications, events, reloading the MCP integration) may fail while Home Assistant is starting; they must not break the tool listing or the MCP session.

## Tests

- Tests run with `pytest` against the modules in `kifli_mcp_connector/rootfs/app` (see `pyproject.toml`). They must not use the network: use `httpx.MockTransport` or the fake servers in the existing tests.
- Bug fixes and new behaviour need a test that fails without the change.
- If several tests share most of their code, prefer `pytest.mark.parametrize` with clear `ids` over duplicated test bodies.
