"""Tests for lab.validate_topo CLI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from lab.topology_contract import GEN_TOPOLOGY_PATH, load_topology, validate_topology
from tests.scaffold_contract import REPO_ROOT


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "lab.validate_topo", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


@pytest.fixture(autouse=True)
def ensure_generated_topo() -> None:
    subprocess.run(["make", "gen-topo"], cwd=REPO_ROOT, check=True, capture_output=True)
    yield


def test_validate_topo_cli_success() -> None:
    result = _run_cli(str(GEN_TOPOLOGY_PATH))
    assert result.returncode == 0, result.stderr


def test_validate_topo_cli_with_ceos_image_flag() -> None:
    result = _run_cli(str(GEN_TOPOLOGY_PATH), "--ceos-image", "ceos:4.36.2F")
    assert result.returncode == 0, result.stderr


def test_validate_topo_cli_with_mgmt_ipv6_subnet_flag() -> None:
    result = _run_cli(str(GEN_TOPOLOGY_PATH), "--mgmt-ipv6-subnet", "2001:db8:127::/64")
    assert result.returncode == 0, result.stderr


def test_validate_topo_cli_fails_on_ipv6_subnet_mismatch() -> None:
    result = _run_cli(str(GEN_TOPOLOGY_PATH), "--mgmt-ipv6-subnet", "2001:db8:99::/64")
    assert result.returncode == 1
    assert "mgmt.ipv6-subnet" in result.stderr


def test_validate_topo_cli_fails_on_contract_violation(tmp_path: Path) -> None:
    broken = tmp_path / "broken.clab.yml"
    data = yaml.safe_load(GEN_TOPOLOGY_PATH.read_text(encoding="utf-8"))
    data["topology"]["nodes"]["ceos1-both"]["mgmt-ipv4"] = "10.0.0.1"
    broken.write_text(yaml.dump(data, sort_keys=False), encoding="utf-8")

    errors = validate_topology(data)
    assert errors

    result = _run_cli(str(broken))
    assert result.returncode == 1
    assert "ceos1-both mgmt-ipv4" in result.stderr


def test_validate_topo_cli_missing_file() -> None:
    result = _run_cli("/nonexistent/topo.clab.yml")
    assert result.returncode == 1
    assert "not found" in result.stderr
