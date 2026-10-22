"""Consistency of the add-on config, the run script and the dependencies.

The run script is actually executed in bash, with the bashio functions replaced
by a small stub and ``exec`` intercepted, so these tests check the real
country → endpoint resolution, not a copy of it.
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

# Defined here on purpose, independently of the run script, so a swapped endpoint fails the tests.
EXPECTED_COUNTRY_URLS = {
    "hu": "https://mcp.kifli.hu/mcp",
    "cz": "https://mcp.rohlik.cz/mcp",
    "at": "https://mcp.gurkerl.at/mcp",
    "de": "https://mcp.knuspr.de/mcp",
    "ro": "https://mcp.sezamo.ro/mcp",
}


def _config() -> dict:
    return yaml.safe_load((ADDON / "config.yaml").read_text(encoding="utf-8"))


def _schema_countries() -> list[str]:
    m = re.fullmatch(r"list\(([^)]*)\)\??", _config()["schema"]["country"])
    assert m, "the 'country' schema must be list(...)"
    return m.group(1).split("|")


def _run_branches() -> dict[str, str]:
    text = RUN.read_text(encoding="utf-8")
    return dict(re.findall(r'^\s+([a-z]{2})\) URL="(https://[^"]+)" ;;', text, re.MULTILINE))


# --- static consistency --------------------------------------------------------------------------

def test_every_option_has_a_schema_entry():
    cfg = _config()
    assert set(cfg["options"]) <= set(cfg["schema"])


def test_default_country_is_allowed():
    assert _config()["options"]["country"] in _schema_countries()


def test_run_script_maps_exactly_the_expected_countries():
    assert sorted(_schema_countries()) == sorted(EXPECTED_COUNTRY_URLS)
    assert _run_branches() == EXPECTED_COUNTRY_URLS


# --- dependencies: pinned once, in kifli_mcp_connector/requirements.txt ---------------------------
# A pin inside the Dockerfile is invisible to Dependabot: in #5 it bumped only the tests' copy of
# mcp, which would have left the add-on itself on a version with open security advisories.

def _requirements(path: Path) -> list[str]:
    lines = (line.split("#", 1)[0].strip() for line in path.read_text(encoding="utf-8").splitlines())
    return [line for line in lines if line]


def test_add_on_requirements_pin_the_mcp_stack():
    reqs = _requirements(ADDON / "requirements.txt")
    assert any(re.fullmatch(r"mcp==[0-9.]+", r) for r in reqs)
    assert any(re.fullmatch(r"mcp-proxy==[0-9.]+", r) for r in reqs)


def test_dockerfile_installs_only_the_add_on_requirements():
    dockerfile = (ADDON / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^COPY requirements\.txt ", dockerfile, re.MULTILINE)
    assert re.search(r"pip install .*-r /tmp/requirements\.txt", dockerfile)
    assert not re.search(r'"[A-Za-z0-9_.-]+[=<>~]=', dockerfile), "pin Python packages in requirements.txt only"


def test_tests_use_the_add_on_requirements():
    reqs = _requirements(ROOT / "tests" / "requirements.txt")
    assert "-r ../kifli_mcp_connector/requirements.txt" in reqs
    add_on = {re.split(r"[=<>~!]", r, maxsplit=1)[0] for r in _requirements(ADDON / "requirements.txt")}
    duplicated = [r for r in reqs if re.split(r"[=<>~!]", r, maxsplit=1)[0] in add_on]
    assert not duplicated, f"pinned again in tests/requirements.txt: {duplicated}"


def test_shim_reports_the_add_on_version():
    shim = (ADDON / "rootfs" / "app" / "mcp_schema_shim.py").read_text(encoding="utf-8")
    m = re.search(r'^SERVER_VERSION = "([^"]+)"', shim, re.MULTILINE)
    assert m, "SERVER_VERSION not found"
    assert m.group(1) == _config()["version"], "bump the shim's SERVER_VERSION together with config.yaml"


def test_changelog_has_the_current_version_in_both_languages():
    # Home Assistant shows the changelog on update; both the English and the Hungarian part need an entry
    changelog = (ADDON / "CHANGELOG.md").read_text(encoding="utf-8")
    english, hungarian = changelog.split('<a name="magyar"></a>', 1)
    heading = re.compile(rf"^## {re.escape(_config()['version'])} — \d{{4}}-\d{{2}}-\d{{2}}$", re.MULTILINE)
    assert heading.search(english), "no English changelog entry for the current version"
    assert heading.search(hungarian), "no Hungarian changelog entry for the current version"


# --- Dockerfile base image: without build.yaml the Supervisor passes ONLY BUILD_ARCH (#1) ---------

def _var(text: str, values: dict[str, str]) -> str:
    return re.sub(r"\$\{(\w+)\}|\$(\w+)", lambda m: values.get(m.group(1) or m.group(2), ""), text)


def resolve_base_image(dockerfile: str, build_arch: str) -> str:
    """The base image the build starts from when it only gets BUILD_ARCH (as from the Supervisor)."""
    head = dockerfile.split("\nFROM ", 1)[0]
    values = {"BUILD_ARCH": build_arch}
    for name, default in re.findall(r"^ARG\s+(\w+)(?:=(\S*))?", head, re.MULTILINE):
        if name not in values:  # a passed build arg overrides the default
            values[name] = _var(default or "", values)
    m = re.search(r"^FROM\s+(\S+)", dockerfile, re.MULTILINE)
    assert m, "no FROM in the Dockerfile"
    return _var(m.group(1), values)


@pytest.mark.parametrize("arch", _config()["arch"])
def test_base_image_follows_build_arch(arch):
    image = resolve_base_image((ADDON / "Dockerfile").read_text(encoding="utf-8"), arch)
    assert image.startswith(f"ghcr.io/home-assistant/{arch}-base:"), (
        f"on {arch} the build would start from {image}, which only exists for another architecture")


# --- the run script at runtime -------------------------------------------------------------------

BASHIO_STUB = r"""
bashio::config() { local n="CFG_$1"; printf '%s' "${!n-}"; }
bashio::config.has_value() { local n="CFG_$1"; [ -n "${!n-}" ] && [ "${!n}" != "null" ]; }
bashio::config.true() { local n="CFG_$1"; [ "${!n-}" = "true" ]; }
bashio::log.info() { :; }
bashio::log.warning() { echo "WARNING: $*" >&2; }
bashio::log.fatal() { echo "FATAL: $*" >&2; }
exec() {
  echo "KIFLI_MCP_URL=${KIFLI_MCP_URL}"
  echo "KIFLI_PORT=${KIFLI_PORT}"
  echo "KIFLI_NEW_TOOLS_ENABLED=${KIFLI_NEW_TOOLS_ENABLED-}"
  exit 0
}
source "$1"
"""


def _run(**cfg: str) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", ""), **{f"CFG_{k}": v for k, v in cfg.items()}}
    return subprocess.run(
        [BASH, "-c", BASHIO_STUB, "run-test", RUN.as_posix()],
        env=env, capture_output=True, text=True, timeout=30, check=False,
    )


needs_bash = pytest.mark.skipif(BASH is None, reason="bash not available")


@needs_bash
@pytest.mark.parametrize(("country", "expected_url"), EXPECTED_COUNTRY_URLS.items())
def test_run_script_resolves_each_country(country, expected_url):
    res = _run(port="42783", country=country)
    assert res.returncode == 0, res.stderr
    assert f"KIFLI_MCP_URL={expected_url}" in res.stdout.splitlines()
    assert "KIFLI_PORT=42783" in res.stdout.splitlines()


@needs_bash
@pytest.mark.parametrize("country", ["", "null"])
def test_run_script_defaults_to_hungary(country):
    # upgrading a pre-1.2.0 configuration that has no 'country'
    res = _run(port="42783", country=country)
    assert res.returncode == 0, res.stderr
    assert f"KIFLI_MCP_URL={EXPECTED_COUNTRY_URLS['hu']}" in res.stdout.splitlines()


@needs_bash
def test_mcp_url_overrides_country():
    res = _run(port="42783", country="cz", mcp_url="https://mcp.example.test/mcp")
    assert "KIFLI_MCP_URL=https://mcp.example.test/mcp" in res.stdout.splitlines()


@needs_bash
def test_null_mcp_url_is_ignored():
    res = _run(port="42783", country="at", mcp_url="null")
    assert f"KIFLI_MCP_URL={EXPECTED_COUNTRY_URLS['at']}" in res.stdout.splitlines()


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


@needs_bash
@pytest.mark.parametrize(("value", "expected"), [("true", "true"), ("false", "false"), (None, "false")])
def test_new_tools_enabled_is_exported(value, expected):
    cfg = {"port": "42783", "country": "hu"}
    if value is not None:
        cfg["new_tools_enabled"] = value
    res = _run(**cfg)
    assert res.returncode == 0, res.stderr
    assert f"KIFLI_NEW_TOOLS_ENABLED={expected}" in res.stdout.splitlines()
