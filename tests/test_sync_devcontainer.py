"""Tests for sync_devcontainer."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from lab.sync_devcontainer import (
    read_clab_version_from_devcontainer,
    read_clab_version_from_makefile,
    sync_devcontainer,
)
from tests.scaffold_contract import REPO_ROOT

MAKEFILE = REPO_ROOT / "Makefile"
DEVCONTAINER_JSON = REPO_ROOT / ".devcontainer" / "devcontainer.json"


def test_read_clab_version_from_makefile() -> None:
    version = read_clab_version_from_makefile(MAKEFILE)
    assert version == read_clab_version_from_devcontainer(DEVCONTAINER_JSON)


def test_sync_devcontainer_is_idempotent() -> None:
    before = DEVCONTAINER_JSON.read_text(encoding="utf-8")
    assert sync_devcontainer(makefile=MAKEFILE, devcontainer_json=DEVCONTAINER_JSON)
    assert DEVCONTAINER_JSON.read_text(encoding="utf-8") == before


def test_sync_devcontainer_check_passes_when_in_sync() -> None:
    sync_devcontainer(makefile=MAKEFILE, devcontainer_json=DEVCONTAINER_JSON)
    assert sync_devcontainer(
        makefile=MAKEFILE,
        devcontainer_json=DEVCONTAINER_JSON,
        check=True,
    )


def test_sync_devcontainer_check_fails_when_out_of_sync(tmp_path: Path) -> None:
    makefile = tmp_path / "Makefile"
    devcontainer = tmp_path / "devcontainer.json"
    makefile.write_text("CLAB_VERSION  ?= 9.99.9\n", encoding="utf-8")
    devcontainer.write_text(
        DEVCONTAINER_JSON.read_text(encoding="utf-8").replace('"0.78.0"', '"0.77.0"'),
        encoding="utf-8",
    )
    assert not sync_devcontainer(
        makefile=makefile,
        devcontainer_json=devcontainer,
        check=True,
    )


def test_sync_devcontainer_updates_version(tmp_path: Path) -> None:
    makefile = tmp_path / "Makefile"
    devcontainer = tmp_path / "devcontainer.json"
    makefile.write_text("CLAB_VERSION  ?= 9.99.9\n", encoding="utf-8")
    devcontainer.write_text(
        DEVCONTAINER_JSON.read_text(encoding="utf-8").replace('"0.78.0"', '"0.77.0"'),
        encoding="utf-8",
    )
    assert sync_devcontainer(makefile=makefile, devcontainer_json=devcontainer)
    assert read_clab_version_from_devcontainer(devcontainer) == "9.99.9"


def test_sync_devcontainer_cli_check() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "lab.sync_devcontainer", "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
