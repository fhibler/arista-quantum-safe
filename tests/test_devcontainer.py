"""Devcontainer contract tests (Session 4)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.scaffold_contract import REPO_ROOT

DEVCONTAINER_JSON = REPO_ROOT / ".devcontainer" / "devcontainer.json"
DEVCONTAINER_LOCK = REPO_ROOT / ".devcontainer" / "devcontainer-lock.json"


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


def test_devcontainer_base_image_unchanged() -> None:
    text = _devcontainer_text()
    assert '"image": "mcr.microsoft.com/devcontainers/base:noble"' in text


def test_devcontainer_remote_user_root() -> None:
    text = _devcontainer_text()
    assert '"remoteUser": "root"' in text
    assert '"containerUser": "root"' in text


def test_devcontainer_preserves_claude_and_ansible_features() -> None:
    text = _devcontainer_text()
    assert "ghcr.io/stu-bell/devcontainer-features/claude-code:0" in text
    assert "ghcr.io/devcontainers-extra/features/ansible:2" in text
    assert "ghcr.io/hspaans/devcontainer-features/ansible-lint:2" in text


def test_devcontainer_preserves_arista_proxy_env() -> None:
    text = _devcontainer_text()
    assert '"ANTHROPIC_BASE_URL": "https://ai-proxy.infra.corp.arista.io/"' in text
    assert '"ANSIBLE_CONFIG": "${containerWorkspaceFolder}/ansible.cfg"' in text


def test_devcontainer_preserves_mounts() -> None:
    text = _devcontainer_text()
    assert ".claude" in text
    assert ".ai-proxy-api-key" in text


def test_devcontainer_containerlab_extension() -> None:
    text = _devcontainer_text()
    assert "srl-labs.vscode-containerlab" in text


def test_devcontainer_docker_in_docker_pinned() -> None:
    dind = _devcontainer_feature_options("ghcr.io/devcontainers/features/docker-in-docker:2")
    assert dind["version"] == "26.1.5"
    assert dind["moby"] is False
    assert dind["installDockerBuildx"] is True
    assert dind["installDockerComposeSwitch"] is False
    assert dind["dockerDashComposeVersion"] == "v2"


def test_devcontainer_post_create_command() -> None:
    text = _devcontainer_text()
    assert "postCreateCommand" in text
    assert "get.containerlab.dev" in text
    assert "iproute2" in text
    assert "iputils-ping" in text
    assert "tcpdump" in text
    assert "requirements-dev.txt" in text
