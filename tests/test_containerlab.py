"""Containerlab integration tests.

Skipped by default via pyproject.toml addopts. Run explicitly after devcontainer rebuild:

    pytest -m containerlab
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.scaffold_contract import REPO_ROOT

GEN_TOPO = REPO_ROOT / "lab" / ".gen.qkd-macsec-radius.clab.yml"


@pytest.fixture(scope="module")
def generated_topology() -> Path:
    subprocess.run(["make", "gen-topo"], cwd=REPO_ROOT, check=True, capture_output=True, text=True)
    assert GEN_TOPO.is_file(), "make gen-topo did not produce generated topology"
    return GEN_TOPO


@pytest.mark.containerlab
@pytest.mark.skipif(shutil.which("containerlab") is None, reason="containerlab CLI not in PATH")
def test_topology_containerlab_dry_run(generated_topology: Path) -> None:
    result = subprocess.run(
        ["containerlab", "deploy", "--dry-run", "-t", str(generated_topology)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.containerlab
@pytest.mark.skipif(shutil.which("containerlab") is None, reason="containerlab CLI not in PATH")
def test_containerlab_version() -> None:
    result = subprocess.run(
        ["containerlab", "version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "containerlab" in result.stdout.lower() or result.stdout.strip()
