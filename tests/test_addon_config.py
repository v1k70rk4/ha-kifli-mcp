"""Az add-on konfiguráció, a run script és a függőségek összhangja.

A run scriptet ténylegesen lefuttatjuk bash-ben, a bashio függvényeket egy
kis stubbal helyettesítve, az ``exec``-et pedig elfogva – így az ország →
végpont feloldás valódi viselkedését nézzük, nem egy másolatát.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "kifli_mcp_connector"
RUN = ADDON / "rootfs" / "etc" / "services.d" / "kifli-mcp" / "run"
BASH = shutil.which("bash")


def _config() -> dict:
    return yaml.safe_load((ADDON / "config.yaml").read_text(encoding="utf-8"))


def _schema_countries() -> list[str]:
    m = re.fullmatch(r"list\(([^)]*)\)\??", _config()["schema"]["country"])
    assert m, "a 'country' séma list(...) legyen"
    return m.group(1).split("|")


def _run_branches() -> dict[str, str]:
    text = RUN.read_text(encoding="utf-8")
    return dict(re.findall(r'^\s+([a-z]{2})\) URL="(https://[^"]+)" ;;', text, re.MULTILINE))


# --- statikus összhang --------------------------------------------------------------------------

def test_every_option_has_a_schema_entry():
    cfg = _config()
    assert set(cfg["options"]) <= set(cfg["schema"])


def test_default_country_is_allowed():
    assert _config()["options"]["country"] in _schema_countries()


def test_run_script_maps_exactly_the_schema_countries():
    branches = _run_branches()
    assert sorted(branches) == sorted(_schema_countries())
    for url in branches.values():
        assert re.fullmatch(r"https://mcp\.[a-z]+\.[a-z]{2}/mcp", url)


def test_test_requirements_match_dockerfile_pins():
    docker = dict(re.findall(r'"([a-z0-9-]+)==([0-9.]+)"', (ADDON / "Dockerfile").read_text(encoding="utf-8")))
    reqs = dict(re.findall(r"^([a-z0-9-]+)==([0-9.]+)", (ROOT / "tests" / "requirements.txt").read_text(
        encoding="utf-8"), re.MULTILINE))
    assert "mcp" in reqs
    for name, version in reqs.items():
        if name in docker:
            assert docker[name] == version, f"{name}: Dockerfile {docker[name]} ≠ tests/requirements.txt {version}"


def test_shim_reports_the_add_on_version():
    shim = (ADDON / "rootfs" / "app" / "mcp_schema_shim.py").read_text(encoding="utf-8")
    m = re.search(r'^SERVER_VERSION = "([^"]+)"', shim, re.MULTILINE)
    assert m, "SERVER_VERSION nem található"
    assert m.group(1) == _config()["version"], "a config.yaml verzióemelésekor a shim SERVER_VERSION-jét is emeld"


def test_changelog_has_the_current_version_in_both_languages():
    # a Home Assistant frissítéskor ezt mutatja; az angol és a magyar részben is legyen bejegyzés
    changelog = (ADDON / "CHANGELOG.md").read_text(encoding="utf-8")
    english, hungarian = changelog.split('<a name="magyar"></a>', 1)
    heading = re.compile(rf"^## {re.escape(_config()['version'])} — \d{{4}}-\d{{2}}-\d{{2}}$", re.MULTILINE)
    assert heading.search(english), "hiányzik az angol changelog-bejegyzés az aktuális verzióhoz"
    assert heading.search(hungarian), "hiányzik a magyar changelog-bejegyzés az aktuális verzióhoz"


# --- a Dockerfile alapképe: a Supervisor build.yaml nélkül CSAK a BUILD_ARCH-ot adja át (#1) -----

def _var(text: str, values: dict[str, str]) -> str:
    return re.sub(r"\$\{(\w+)\}|\$(\w+)", lambda m: values.get(m.group(1) or m.group(2), ""), text)


def resolve_base_image(dockerfile: str, build_arch: str) -> str:
    """Melyik alapképből indul a build, ha csak BUILD_ARCH-ot kap (mint a Supervisortól)."""
    head = dockerfile.split("\nFROM ", 1)[0]
    values = {"BUILD_ARCH": build_arch}
    for name, default in re.findall(r"^ARG\s+(\w+)(?:=(\S*))?", head, re.MULTILINE):
        if name not in values:  # az átadott build-arg felülírja az alapértelmezést
            values[name] = _var(default or "", values)
    m = re.search(r"^FROM\s+(\S+)", dockerfile, re.MULTILINE)
    assert m, "nincs FROM a Dockerfile-ban"
    return _var(m.group(1), values)


@pytest.mark.parametrize("arch", _config()["arch"])
def test_base_image_follows_build_arch(arch):
    image = resolve_base_image((ADDON / "Dockerfile").read_text(encoding="utf-8"), arch)
    assert image.startswith(f"ghcr.io/home-assistant/{arch}-base:"), (
        f"{arch}-on a(z) {image} alapképből buildelne – az csak más architektúrára létezik")


# --- a run script futás közben ------------------------------------------------------------------

BASHIO_STUB = r"""
bashio::config() { local n="CFG_$1"; printf '%s' "${!n-}"; }
bashio::config.has_value() { local n="CFG_$1"; [ -n "${!n-}" ] && [ "${!n}" != "null" ]; }
bashio::log.info() { :; }
bashio::log.warning() { echo "WARNING: $*" >&2; }
bashio::log.fatal() { echo "FATAL: $*" >&2; }
exec() { echo "KIFLI_MCP_URL=${KIFLI_MCP_URL}"; echo "KIFLI_PORT=${KIFLI_PORT}"; exit 0; }
source "$1"
"""


def _run(**cfg: str) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", ""), **{f"CFG_{k}": v for k, v in cfg.items()}}
    return subprocess.run(
        [BASH, "-c", BASHIO_STUB, "run-test", RUN.as_posix()],
        env=env, capture_output=True, text=True, timeout=30, check=False,
    )


needs_bash = pytest.mark.skipif(BASH is None, reason="nincs bash")


@needs_bash
@pytest.mark.parametrize("country", list(_run_branches()))
def test_run_script_resolves_each_country(country):
    res = _run(port="42783", country=country)
    assert res.returncode == 0, res.stderr
    assert f"KIFLI_MCP_URL={_run_branches()[country]}" in res.stdout
    assert "KIFLI_PORT=42783" in res.stdout


@needs_bash
@pytest.mark.parametrize("country", ["", "null"])
def test_run_script_defaults_to_hungary(country):
    # 1.2.0 előtti, 'country' nélküli konfiguráció frissítése
    res = _run(port="42783", country=country)
    assert res.returncode == 0, res.stderr
    assert "KIFLI_MCP_URL=https://mcp.kifli.hu/mcp" in res.stdout


@needs_bash
def test_mcp_url_overrides_country():
    res = _run(port="42783", country="cz", mcp_url="https://mcp.example.test/mcp")
    assert "KIFLI_MCP_URL=https://mcp.example.test/mcp" in res.stdout


@needs_bash
def test_null_mcp_url_is_ignored():
    res = _run(port="42783", country="at", mcp_url="null")
    assert "KIFLI_MCP_URL=https://mcp.gurkerl.at/mcp" in res.stdout


@needs_bash
def test_unknown_country_stops_the_add_on():
    res = _run(port="42783", country="sk")
    assert res.returncode == 1
    assert "FATAL" in res.stderr
    assert "KIFLI_MCP_URL" not in res.stdout


@needs_bash
def test_leftover_email_password_only_warns():
    res = _run(port="42783", country="hu", email="user@example.com")
    assert res.returncode == 0, res.stderr
    assert "WARNING" in res.stderr
    assert "email" in res.stderr
