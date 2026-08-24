"""Devcontainer contract tests."""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.scaffold_contract import REPO_ROOT

DEVCONTAINER_JSON = REPO_ROOT / ".devcontainer" / "devcontainer.json"
DEVCONTAINER_DOCKERFILE = REPO_ROOT / ".devcontainer" / "Dockerfile"
DEVCONTAINER_LOCK = REPO_ROOT / ".devcontainer" / "devcontainer-lock.json"

TRIXIE_BASE = "mcr.microsoft.com/devcontainers/python:3-trixie"


def _devcontainer_text() -> str:
    return DEVCONTAINER_JSON.read_text(encoding="utf-8")


def test_devcontainer_json_exists() -> None:
    assert DEVCONTAINER_JSON.is_file()


def test_devcontainer_dockerfile_exists() -> None:
    assert DEVCONTAINER_DOCKERFILE.is_file()


def test_devcontainer_lock_exists() -> None:
    assert DEVCONTAINER_LOCK.is_file()


def test_devcontainer_builds_trixie_dind_slim_fork() -> None:
    text = _devcontainer_text()
    assert '"build"' in text
    assert '"dockerfile": "Dockerfile"' in text
    assert "CLAB_VERSION" not in text
    dockerfile = DEVCONTAINER_DOCKERFILE.read_text(encoding="utf-8")
    assert f"FROM {TRIXIE_BASE}" in dockerfile
    assert "COPY" not in dockerfile or "dclab" not in dockerfile.split("COPY", 1)[-1]


def test_devcontainer_installs_containerlab_latest() -> None:
    dockerfile = DEVCONTAINER_DOCKERFILE.read_text(encoding="utf-8")
    assert "get.containerlab.dev" in dockerfile
    assert "ARG CLAB_VERSION" not in dockerfile
    assert "-v ${CLAB_VERSION}" not in dockerfile
    assert '-- -v' not in dockerfile


def test_devcontainer_remote_user_root() -> None:
    text = _devcontainer_text()
    assert '"remoteUser": "root"' in text
    assert '"containerUser": "root"' in text


def test_devcontainer_has_no_ansible_scaffold() -> None:
    text = _devcontainer_text()
    assert "ghcr.io/devcontainers-extra/features/ansible:2" not in text
    assert "ghcr.io/hspaans/devcontainer-features/ansible-lint:2" not in text
    assert "redhat.ansible" not in text
    assert "ANSIBLE_CONFIG" not in text
    assert "ansible.cfg" not in text


def test_devcontainer_no_ai_proxy_env() -> None:
    text = _devcontainer_text()
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
    assert "ghcr.io/devcontainers/features/docker-in-docker:2" in text
    assert "docker-outside-of-docker" not in text
    assert "runArgs" not in text
    assert "LOCAL_WORKSPACE_FOLDER" not in text
    assert "mcr.microsoft.com/devcontainers/base:noble" not in text


def test_devcontainer_has_no_node_feature() -> None:
    text = _devcontainer_text()
    assert "ghcr.io/devcontainers/features/node" not in text
    lock = json.loads(DEVCONTAINER_LOCK.read_text(encoding="utf-8"))
    assert "ghcr.io/devcontainers/features/node:2.0.0" not in lock.get("features", {})


def test_devcontainer_dockerfile_installs_gnmic() -> None:
    dockerfile = DEVCONTAINER_DOCKERFILE.read_text(encoding="utf-8")
    test_runner = (REPO_ROOT / "docker" / "test-runner" / "Dockerfile").read_text(encoding="utf-8")
    dev_match = re.search(r"ARG GNMIC_VERSION=(\S+)", dockerfile)
    runner_match = re.search(r"ARG GNMIC_VERSION=(\S+)", test_runner)
    assert dev_match is not None
    assert runner_match is not None
    assert dev_match.group(1) == runner_match.group(1)
    assert "install -m 755 /tmp/gnmic /usr/local/bin/gnmic" in dockerfile


def test_test_runner_harness_uses_container_python() -> None:
    harness = (REPO_ROOT / "docker" / "test-runner" / "harness-entrypoint.sh").read_text(
        encoding="utf-8"
    )
    requirements_lab = (REPO_ROOT / "requirements-lab.txt").read_text(encoding="utf-8")
    test_runner = (REPO_ROOT / "docker" / "test-runner" / "Dockerfile").read_text(encoding="utf-8")

    assert 'PYTHON=python3' in harness
    assert "scripts/check_lab_imports.py --check-imports" in harness
    assert "requirements-lab.txt" in harness
    assert 'make PYTHON="$PYTHON"' in harness
    assert "requirements-dev.txt" not in harness
    assert "PyYAML>=" in requirements_lab
    assert "py3-yaml" in test_runner


def test_devcontainer_lock_has_dind_not_dood() -> None:
    lock = json.loads(DEVCONTAINER_LOCK.read_text(encoding="utf-8"))
    features = lock.get("features", {})
    assert "ghcr.io/devcontainers/features/docker-in-docker:2" in features
    assert "ghcr.io/devcontainers/features/docker-outside-of-docker:1" not in features
