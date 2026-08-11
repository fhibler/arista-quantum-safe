"""Optional Docker-based smoke tests for RADIUS image artifacts."""

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
            "quantum-safe-radius:test",
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
            "quantum-safe-radius:test-run",
            "-f",
            "docker/radius/Dockerfile",
            ".",
        ],
        check=True,
        timeout=300,
    )
    result = subprocess.run(
        ["docker", "run", "--rm", "quantum-safe-radius:test-run", "radiusd", "-C"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "clients.conf" in combined or result.returncode == 0
