from pathlib import Path

import pytest

from tests.scaffold_contract import GITIGNORE_PATTERNS, REQUIRED_PATHS


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("relative_path", REQUIRED_PATHS)
def test_required_paths_exist(repo_root: Path, relative_path: str) -> None:
    path = repo_root / relative_path
    assert path.exists(), f"missing {relative_path}"


def test_gitignore_patterns(repo_root: Path) -> None:
    content = (repo_root / ".gitignore").read_text(encoding="utf-8")
    for pattern in GITIGNORE_PATTERNS:
        assert pattern in content, f".gitignore must include {pattern!r}"


def test_env_example_has_arista_token(repo_root: Path) -> None:
    content = (repo_root / ".env.example").read_text(encoding="utf-8")
    assert "ARISTA_TOKEN=" in content


def test_ansible_cfg_points_at_inventory(repo_root: Path) -> None:
    content = (repo_root / "ansible.cfg").read_text(encoding="utf-8")
    assert "inventory = ./inventory" in content
