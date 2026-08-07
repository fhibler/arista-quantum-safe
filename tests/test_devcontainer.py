"""Devcontainer contract tests."""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.scaffold_contract import REPO_ROOT

DEVCONTAINER_JSON = REPO_ROOT / ".devcontainer" / "devcontainer.json"
DEVCONTAINER_LOCK = REPO_ROOT / ".devcontainer" / "devcontainer-lock.json"

CLAB_DIND_IMAGE = "ghcr.io/srl-labs/containerlab/devcontainer-dind-slim:0.77.0"


def _devcontainer_text() -> str:
    return DEVCONTAINER_JSON.read_text(encoding="utf-8")


def _devcontainer_feature_options(feature: str) -> dict:
    """Extract JSON object for a devcontainer feature block (JSONC-tolerant)."""
    pattern = rf'"{re.escape(feature)}":\s*(\{{[^}}]+\}})'
    match = re.search(pattern, _devcontainer_text(), re.DOTALL)
    assert match, f"missing feature block: {feature}"
    return json.loads(match.group(1))


def test_devcontainer_json_exists() -> None:
    assert DEVCONTAINER_JSON.is_file()


def test_devcontainer_lock_exists() -> None:
    assert DEVCONTAINER_LOCK.is_file()


def test_devcontainer_uses_containerlab_dind_slim_image() -> None:
    text = _devcontainer_text()
    assert f'"image": "{CLAB_DIND_IMAGE}"' in text


def test_devcontainer_remote_user_root() -> None:
    text = _devcontainer_text()
    assert '"remoteUser": "root"' in text
    assert '"containerUser": "root"' in text


def test_devcontainer_preserves_ansible_features() -> None:
    text = _devcontainer_text()
    assert "ghcr.io/devcontainers-extra/features/ansible:2" in text
    assert "ghcr.io/hspaans/devcontainer-features/ansible-lint:2" in text


def test_devcontainer_ansible_config_env() -> None:
    text = _devcontainer_text()
    assert '"ANSIBLE_CONFIG": "${containerWorkspaceFolder}/ansible.cfg"' in text
    assert "ANTHROPIC_BASE_URL" not in text


def test_devcontainer_no_claude_mounts() -> None:
    text = _devcontainer_text()
    assert ".claude" not in text
    assert ".ai-proxy-api-key" not in text


def test_devcontainer_containerlab_extension() -> None:
    text = _devcontainer_text()
    assert "srl-labs.vscode-containerlab" in text


def test_devcontainer_post_create_command() -> None:
    text = _devcontainer_text()
    assert "postCreateCommand" in text
    assert "requirements-dev.txt" in text
    assert "get.containerlab.dev" not in text
    assert "docker restart" not in text


def test_devcontainer_uses_dind_not_dood() -> None:
    text = _devcontainer_text()
    assert "devcontainer-dind-slim" in text
    assert "docker-outside-of-docker" not in text
    assert "docker-in-docker" not in text
    assert "runArgs" not in text
    assert "LOCAL_WORKSPACE_FOLDER" not in text
    assert "mcr.microsoft.com/devcontainers/base:noble" not in text


def test_devcontainer_lock_has_no_dood_or_dind_features() -> None:
    lock = json.loads(DEVCONTAINER_LOCK.read_text(encoding="utf-8"))
    features = lock.get("features", {})
    assert "ghcr.io/devcontainers/features/docker-outside-of-docker:1" not in features
    assert "ghcr.io/devcontainers/features/docker-in-docker:2" not in features


def test_dood_backup_preserved_under_tmp() -> None:
    backup = REPO_ROOT / "tmp" / "dood" / "devcontainer.json"
    assert backup.is_file()
    text = backup.read_text(encoding="utf-8")
    assert "docker-outside-of-docker" in text
