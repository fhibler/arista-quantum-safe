"""Optional Docker-based smoke tests for Session 2 artifacts."""

import shutil
import subprocess

import pytest


pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="docker CLI not available",
)


def _docker_available() -> bool:
    try:
        subprocess.run(
            ["docker", "info"],
            check=True,
            capture_output=True,
            timeout=30,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return False


@pytest.mark.skipif(not _docker_available(), reason="docker daemon not running")
def test_build_radius_image() -> None:
    subprocess.run(
        [
            "docker",
            "build",
            "-t",
            "qkd-radius:test",
            "-f",
            "docker/radius/Dockerfile",
            ".",
        ],
        check=True,
        timeout=300,
    )


@pytest.mark.skipif(not _docker_available(), reason="docker daemon not running")
def test_radius_config_loads() -> None:
    subprocess.run(
        [
            "docker",
            "build",
            "-t",
            "qkd-radius:test-run",
            "-f",
            "docker/radius/Dockerfile",
            ".",
        ],
        check=True,
        timeout=300,
    )
    result = subprocess.run(
        ["timeout", "5", "docker", "run", "--rm", "qkd-radius:test-run", "radiusd", "-X"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    combined = result.stdout + result.stderr
    assert "Ready to process requests" in combined
    assert "including configuration file /etc/raddb/clients.conf" in combined
