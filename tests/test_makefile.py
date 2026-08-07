"""Tests for Makefile topology generation and lifecycle targets."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from lab.topology_contract import (
    DEFAULT_CEOS_IMAGE,
    DEFAULT_MGMT_SUBNET,
    GEN_TOPOLOGY_PATH,
    TOPOLOGY_PATH,
    load_topology,
    validate_topology,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = REPO_ROOT / "Makefile"


def _run_make(*targets: str, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = ["make", "-C", str(REPO_ROOT), *targets]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
        check=check,
    )


def test_makefile_exists() -> None:
    assert MAKEFILE.is_file()


@pytest.mark.parametrize(
    "target",
    [
        "help",
        "gen-topo",
        "validate-topo",
        "test",
        "check-ceos-image",
        "import-ceos",
        "import-ceos-help",
        "download-ceos",
        "download-ceos-help",
        "build-radius",
        "deploy",
        "destroy",
        "redeploy",
        "inspect",
        "graph",
        "ssh-ceos1",
        "ssh-ceos2",
        "test-radius",
        "test-hosts",
    ],
)
def test_make_help_lists_target(target: str) -> None:
    result = _run_make("help")
    assert target in result.stdout


def test_gen_topo_default_image() -> None:
    _run_make("gen-topo")
    assert GEN_TOPOLOGY_PATH.is_file()
    data = load_topology(GEN_TOPOLOGY_PATH)
    image = data["topology"]["kinds"]["arista_ceos"]["image"]
    assert image == DEFAULT_CEOS_IMAGE
    assert data["mgmt"]["ipv4-subnet"] == DEFAULT_MGMT_SUBNET


def test_gen_topo_custom_ceos_image() -> None:
    custom = "ceos:5.0.0F"
    _run_make("gen-topo", f"CEOS_IMAGE={custom}")
    data = load_topology(GEN_TOPOLOGY_PATH)
    assert data["topology"]["kinds"]["arista_ceos"]["image"] == custom
    errors = validate_topology(data, ceos_image=custom)
    assert errors == []


def test_gen_topo_custom_mgmt_subnet() -> None:
    custom = "192.168.28.0/24"
    _run_make("gen-topo", f"MGMT_SUBNET={custom}")
    data = load_topology(GEN_TOPOLOGY_PATH)
    assert data["mgmt"]["ipv4-subnet"] == custom
    assert data["topology"]["nodes"]["radius"]["mgmt-ipv4"] == "192.168.28.50"
    errors = validate_topology(data, mgmt_subnet=custom)
    assert errors == []


def test_gen_topo_substitutes_placeholders() -> None:
    _run_make("gen-topo")
    src = TOPOLOGY_PATH.read_text(encoding="utf-8")
    gen = GEN_TOPOLOGY_PATH.read_text(encoding="utf-8")
    assert "${CEOS_IMAGE}" in src
    assert "${MGMT_SUBNET}" in src
    assert "${CEOS_IMAGE}" not in gen
    assert "${MGMT_SUBNET}" not in gen
    assert f"image: {DEFAULT_CEOS_IMAGE}" in gen
    assert f"ipv4-subnet: {DEFAULT_MGMT_SUBNET}" in gen


def test_validate_topo_passes_via_make() -> None:
    result = _run_make("validate-topo")
    assert result.returncode == 0
    assert GEN_TOPOLOGY_PATH.is_file()


def test_validate_topo_fails_on_contract_violation(tmp_path: Path) -> None:
    _run_make("gen-topo")
    broken = tmp_path / "broken.clab.yml"
    broken.write_text(GEN_TOPOLOGY_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    data = yaml.safe_load(broken.read_text(encoding="utf-8"))
    data["topology"]["nodes"]["ceos1"]["mgmt-ipv4"] = "10.0.0.1"
    broken.write_text(yaml.dump(data, sort_keys=False), encoding="utf-8")

    errors = validate_topology(load_topology(broken))
    assert any("ceos1 mgmt-ipv4" in err for err in errors)


def test_render_preserves_yaml_structure() -> None:
    _run_make("gen-topo")
    data = yaml.safe_load(GEN_TOPOLOGY_PATH.read_text(encoding="utf-8"))
    assert data["topology"]["nodes"]["radius"]["image"] == "qkd-radius:latest"
    assert data["topology"]["kinds"]["arista_ceos"]["image"] == DEFAULT_CEOS_IMAGE


def test_import_ceos_help_output() -> None:
    result = _run_make("import-ceos-help")
    assert "docker import download/cEOS64-lab-" in result.stdout
    assert "docker import download/cEOSarm-lab-" in result.stdout
    assert "make download-ceos" in result.stdout


def test_download_ceos_help_output() -> None:
    result = _run_make("download-ceos-help")
    assert "ARISTA_TOKEN" in result.stdout
    assert "ardl get eos" in result.stdout
    assert ".env.example" in result.stdout


def test_download_ceos_fails_without_token(tmp_path: Path) -> None:
    dotenv = REPO_ROOT / ".env"
    had_dotenv = dotenv.exists()
    prior = dotenv.read_text(encoding="utf-8") if had_dotenv else None
    dotenv.unlink(missing_ok=True)
    empty_download = tmp_path / "empty-download"
    empty_download.mkdir()
    env = {k: v for k, v in os.environ.items() if k != "ARISTA_TOKEN"}
    env["CEOS_DOWNLOAD_DIR"] = str(empty_download)
    env["ARISTA_TOKEN"] = ""
    try:
        result = _run_make("download-ceos", env=env, check=False)
        assert result.returncode != 0
        assert "ARISTA_TOKEN not set" in result.stdout + result.stderr
    finally:
        if had_dotenv and prior is not None:
            dotenv.write_text(prior, encoding="utf-8")


def test_download_ceos_loads_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Token in .env satisfies check when shell env has no ARISTA_TOKEN."""
    dotenv = REPO_ROOT / ".env"
    had_dotenv = dotenv.exists()
    prior = dotenv.read_text(encoding="utf-8") if had_dotenv else None
    dotenv.write_text("ARISTA_TOKEN=fake-token-from-dotenv\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "ARISTA_TOKEN"}
    try:
        result = _run_make("download-ceos", env=env, check=False)
        combined = result.stdout + result.stderr
        assert "ARISTA_TOKEN not set" not in combined
    finally:
        if had_dotenv and prior is not None:
            dotenv.write_text(prior, encoding="utf-8")
        else:
            dotenv.unlink(missing_ok=True)


def test_download_ceos_recipe_sources_dotenv() -> None:
    content = MAKEFILE.read_text(encoding="utf-8")
    assert "[ -f .env ] && . ./.env" in content


def test_download_ceos_recipe_uses_download_dir() -> None:
    content = MAKEFILE.read_text(encoding="utf-8")
    assert "CEOS_DOWNLOAD_DIR ?=" in content
    assert 'cd "$(CEOS_DOWNLOAD_DIR)"' in content
    assert '--output "."' in content
    assert 'import eos_downloader' in content
    assert "Tarball already present" in content
    assert "make import-ceos" in content


def test_import_ceos_recipe_imports_local_tarball() -> None:
    content = MAKEFILE.read_text(encoding="utf-8")
    assert "import-ceos:" in content
    assert 'docker import "$$CEOS_TAR" "$(CEOS_IMAGE)"' in content


def test_download_ceos_recipe_installs_eos_downloader_when_missing() -> None:
    content = MAKEFILE.read_text(encoding="utf-8")
    assert "eos-downloader>=0.16.0" in content
    assert "import eos_downloader" in content
    assert "rm -rf .venv && python3 -m venv .venv" in content
    assert "! .venv/bin/ardl" not in content


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available")
def test_check_ceos_image_fails_when_missing() -> None:
    missing = "ceos:nonexistent-test-tag"
    result = _run_make("check-ceos-image", f"CEOS_IMAGE={missing}", check=False)
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "not found" in combined.lower()
    assert "docker import download/cEOS64-lab-" in combined


def test_make_test_recipe_runs_pytest() -> None:
    result = _run_make("-n", "test")
    assert "-m pytest" in result.stdout


def test_validate_topo_uses_cli_module() -> None:
    result = _run_make("-n", "gen-topo")
    assert "lab.render_topo" in result.stdout
    result = _run_make("-n", "validate-topo")
    assert "lab.validate_topo" in result.stdout


def test_makefile_defines_mgmt_subnet() -> None:
    content = MAKEFILE.read_text(encoding="utf-8")
    assert "MGMT_SUBNET   ?=" in content
    assert "172.20.127.0/24" in content
    assert "prepare-ceos-monitor" not in content
    assert "prepare-mgmt-net" not in content


def test_test_radius_recipe_uses_ceos_cli_enable_and_repeat() -> None:
    content = MAKEFILE.read_text(encoding="utf-8")
    assert "test-radius:" in content
    assert "printf 'enable\\nping vrf MGMT" in content
    assert "repeat 3" in content
    assert "successfully authenticated" in content
    assert "Cli -c \"ping vrf MGMT" not in content
    assert "count 3" not in content
