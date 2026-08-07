"""Tests for Makefile topology generation and lifecycle targets (Session 3)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from lab.topology_contract import (
    DEFAULT_CEOS_IMAGE,
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


def _sed_gen_topo(src: Path, dst: Path, ceos_image: str) -> None:
    content = src.read_text(encoding="utf-8")
    content = re.sub(r"image: \$\{CEOS_IMAGE\}", f"image: {ceos_image}", content)
    content = re.sub(r"image: ceos:.*", f"image: {ceos_image}", content)
    dst.write_text(content, encoding="utf-8")


@pytest.fixture(autouse=True)
def cleanup_generated_topo() -> None:
    if GEN_TOPOLOGY_PATH.exists():
        GEN_TOPOLOGY_PATH.unlink()
    yield
    if GEN_TOPOLOGY_PATH.exists():
        GEN_TOPOLOGY_PATH.unlink()


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


def test_gen_topo_custom_ceos_image() -> None:
    custom = "ceos:5.0.0F"
    _run_make("gen-topo", f"CEOS_IMAGE={custom}")
    data = load_topology(GEN_TOPOLOGY_PATH)
    assert data["topology"]["kinds"]["arista_ceos"]["image"] == custom
    errors = validate_topology(data, ceos_image=custom)
    assert errors == []


def test_gen_topo_substitutes_ceos_image_placeholder() -> None:
    _run_make("gen-topo")
    src = TOPOLOGY_PATH.read_text(encoding="utf-8")
    gen = GEN_TOPOLOGY_PATH.read_text(encoding="utf-8")
    assert "${CEOS_IMAGE}" in src
    assert "${CEOS_IMAGE}" not in gen
    assert f"image: {DEFAULT_CEOS_IMAGE}" in gen
    assert src.replace("${CEOS_IMAGE}", DEFAULT_CEOS_IMAGE) == gen


def test_validate_topo_passes_via_make() -> None:
    result = _run_make("validate-topo")
    assert result.returncode == 0
    assert GEN_TOPOLOGY_PATH.is_file()


def test_validate_topo_fails_on_contract_violation(tmp_path: Path) -> None:
    broken = tmp_path / "broken.clab.yml"
    _sed_gen_topo(TOPOLOGY_PATH, broken, DEFAULT_CEOS_IMAGE)
    data = yaml.safe_load(broken.read_text(encoding="utf-8"))
    data["topology"]["nodes"]["ceos1"]["mgmt-ipv4"] = "10.0.0.1"
    broken.write_text(yaml.dump(data, sort_keys=False), encoding="utf-8")

    errors = validate_topology(load_topology(broken))
    assert any("ceos1 mgmt-ipv4" in err for err in errors)


def test_sed_substitution_preserves_yaml_structure(tmp_path: Path) -> None:
    generated = tmp_path / "generated.clab.yml"
    _sed_gen_topo(TOPOLOGY_PATH, generated, "ceos:9.9.9F")
    data = yaml.safe_load(generated.read_text(encoding="utf-8"))
    assert data["topology"]["nodes"]["radius"]["image"] == "qkd-radius:latest"
    assert data["topology"]["kinds"]["arista_ceos"]["image"] == "ceos:9.9.9F"


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


def test_download_ceos_fails_without_token() -> None:
    dotenv = REPO_ROOT / ".env"
    had_dotenv = dotenv.exists()
    prior = dotenv.read_text(encoding="utf-8") if had_dotenv else None
    dotenv.unlink(missing_ok=True)
    env = {k: v for k, v in os.environ.items() if k != "ARISTA_TOKEN"}
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
    assert "CEOS_DOWNLOAD_DIR := download" in content
    assert 'cd "$(CEOS_DOWNLOAD_DIR)"' in content
    assert '--output "."' in content


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
    result = _run_make("-n", "validate-topo")
    assert "lab.validate_topo" in result.stdout
