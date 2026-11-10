"""Containerlab integration tests.

Skipped by default via pyproject.toml addopts. Run explicitly after devcontainer rebuild:

    pytest -m containerlab
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from tests.scaffold_contract import REPO_ROOT

from lab.topology_contract import GEN_TOPOLOGY_PATH

GEN_TOPO = GEN_TOPOLOGY_PATH


@pytest.fixture(scope="module")
def generated_topology() -> Path:
    subprocess.run(["make", "containerlab-gentopo"], cwd=REPO_ROOT, check=True, capture_output=True, text=True)
    assert GEN_TOPO.is_file(), "make containerlab-gentopo did not produce generated topology"
    return GEN_TOPO


@pytest.mark.containerlab
@pytest.mark.skipif(shutil.which("containerlab") is None, reason="containerlab CLI not in PATH")
def test_topology_containerlab_dry_run(generated_topology: Path) -> None:
    # Reconciliation against a deployed lab can fail on its existing interfaces.
    # Use distinct runtime identities while retaining relative bind/config paths.
    identity = uuid4().hex[:12]
    topology = yaml.safe_load(generated_topology.read_text(encoding="utf-8"))
    topology["name"] = f"pytest-{identity}"
    topology["mgmt"]["network"] = f"pytest-{identity}"
    topology["mgmt"]["bridge"] = f"pt{identity}"
    dry_run_topology = generated_topology.with_name(f".gen.pytest-{identity}.clab.yml")
    dry_run_topology.write_text(yaml.safe_dump(topology, sort_keys=False), encoding="utf-8")
    try:
        result = subprocess.run(
            ["containerlab", "deploy", "--dry-run", "-t", str(dry_run_topology)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
    finally:
        dry_run_topology.unlink(missing_ok=True)
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
