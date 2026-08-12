"""Tests for site.yaml central configuration."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.site_config import (
    MKDOCS_PATH,
    SITE_CONFIG_PATH,
    load_site_config,
    mkdocs_site_config_block,
    readme_site_config_block,
)
from tests.scaffold_contract import REPO_ROOT


def test_site_yaml_exists() -> None:
    assert SITE_CONFIG_PATH.is_file()


def test_load_site_config_has_derived_urls() -> None:
    config = load_site_config()
    assert config.repo_url == f"https://{config.repository_host}/{config.repo_slug}"
    assert config.pages_base_url_normalized.endswith("/")
    assert config.edit_uri.startswith("edit/")


def test_readme_and_mkdocs_blocks_are_synced() -> None:
    config = load_site_config()
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    mkdocs = MKDOCS_PATH.read_text(encoding="utf-8")
    assert readme_site_config_block(config) in readme
    assert mkdocs_site_config_block(config) in mkdocs


def test_site_config_check_passes() -> None:
    result = subprocess.run(
        ["python3", "scripts/site_config.py", "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_mkdocs_site_block_is_marked_generated() -> None:
    text = MKDOCS_PATH.read_text(encoding="utf-8")
    assert "# site-config:begin" in text
    assert "Generated from site.yaml" in text
    assert "repo_url:" in text


def test_mkdocs_build_uses_site_yaml_values() -> None:
    try:
        result = subprocess.run(
            ["mkdocs", "build", "--strict"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        pytest.skip("mkdocs not installed")
    if result.returncode != 0 and "No such file or directory: 'mkdocs'" in (
        result.stderr or result.stdout
    ):
        pytest.skip("mkdocs not installed")
    assert result.returncode == 0, result.stderr or result.stdout

    config = load_site_config()
    html = (REPO_ROOT / "site" / "index.html").read_text(encoding="utf-8")
    assert config.repo_url in html
