"""Live lab import graph and requirements-lab.txt contract tests."""

from __future__ import annotations

import subprocess

from scripts.check_lab_imports import (
    REQUIREMENTS_LAB_PATH,
    TEST_LAB_MODULES,
    import_lab_modules,
    parse_requirements_lab,
    required_packages,
    requirements_are_synced,
    third_party_imports,
)
from tests.scaffold_contract import REPO_ROOT


def test_test_lab_modules_are_enumerated() -> None:
    assert "lab.test_lab" in TEST_LAB_MODULES
    assert "lab.topology_contract" in TEST_LAB_MODULES
    assert len(TEST_LAB_MODULES) >= 7


def test_live_lab_third_party_imports_are_yaml_only() -> None:
    assert third_party_imports() == {"yaml"}


def test_requirements_lab_matches_import_graph() -> None:
    assert requirements_are_synced()
    assert parse_requirements_lab() == required_packages()
    assert "PyYAML" in parse_requirements_lab(REQUIREMENTS_LAB_PATH)


def test_live_lab_modules_import() -> None:
    import_lab_modules()


def test_check_lab_imports_script_passes() -> None:
    result = subprocess.run(
        ["python3", "scripts/check_lab_imports.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
