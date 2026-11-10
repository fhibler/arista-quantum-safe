"""QuaDRA installation must work with an existing read-only SWIX bind mount."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from lab.install_quadra import InstallQuadraError, enable_daemon, install_on_node, stage_swix


@pytest.fixture
def swix(tmp_path: Path) -> Path:
    path = tmp_path / "QuaDRA-test.swix"
    path.write_bytes(b"test extension package")
    return path


def result(stdout: str = "", *, code: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


def test_matching_flash_package_is_installed_without_copy(swix: Path) -> None:
    checksum = hashlib.sha256(swix.read_bytes()).hexdigest()
    with patch("lab.install_quadra.container_running", return_value=True), patch(
        "lab.install_quadra.subprocess.run",
        return_value=result(f"{checksum}  /mnt/flash/{swix.name}\n"),
    ) as run, patch(
        "lab.install_quadra.run_cli",
        side_effect=[result(f"{swix.name} A, B"), result(f"{swix.name} A, I, B")],
    ) as cli, patch("lab.install_quadra.enable_daemon") as daemon:
        install_on_node("ceos1-both", clab_name="test", swix_path=str(swix), verbose=False)

    assert run.call_count == 1
    assert run.call_args.args[0] == [
        "docker", "exec", "arista-test-ceos1-both", "sha256sum", f"/mnt/flash/{swix.name}",
    ]
    assert f"extension {swix.name}\n" in cli.call_args.args[1]
    assert "copy installed-extensions boot-extensions" in cli.call_args.args[1]
    daemon.assert_called_once()


@pytest.mark.parametrize("existing", [result(code=1, stderr="No such file"), result("0" * 64)])
def test_missing_or_different_flash_package_is_copied(swix: Path, existing) -> None:
    with patch("lab.install_quadra.subprocess.run", side_effect=[existing, result()]) as run:
        stage_swix("container", "ceos1-both", str(swix), verbose=False)
    assert run.call_args.args[0] == [
        "docker", "cp", str(swix), f"container:/mnt/flash/{swix.name}",
    ]


def test_copy_failure_is_reported(swix: Path) -> None:
    with patch(
        "lab.install_quadra.subprocess.run",
        side_effect=[result(code=1), result(code=1, stderr="device or resource busy")],
    ), pytest.raises(InstallQuadraError, match="ceos1-both: docker cp failed: device or resource busy"):
        stage_swix("container", "ceos1-both", str(swix), verbose=False)


def test_already_installed_package_only_ensures_daemon_running(swix: Path) -> None:
    with patch("lab.install_quadra.container_running", return_value=True), patch(
        "lab.install_quadra.run_cli", return_value=result(f"{swix.name} A, I, B"),
    ), patch("lab.install_quadra.stage_swix") as stage, patch(
        "lab.install_quadra.enable_daemon",
    ) as daemon:
        install_on_node("ceos1-both", clab_name="test", swix_path=str(swix), verbose=False)
    stage.assert_not_called()
    daemon.assert_called_once()


def test_daemon_start_waits_for_agent_registration() -> None:
    with patch(
        "lab.install_quadra.run_cli",
        side_effect=[
            result("Process: quadra (shutdown)"),
            result("Process: quadra (running)\nNo status data stored."),
            result("Agent: quadra (running with PID 3360)"),
        ],
    ) as cli, patch("lab.install_quadra.time.sleep") as sleep:
        enable_daemon("container", "ceos1-both", verbose=False)
    assert "no shutdown" in cli.call_args_list[1].args[1]
    assert cli.call_count == 3
    sleep.assert_called_once()


def test_daemon_start_has_a_bounded_wait() -> None:
    with patch("lab.install_quadra.DAEMON_POLL_ATTEMPTS", 2), patch(
        "lab.install_quadra.run_cli", return_value=result("Process: quadra (shutdown)"),
    ) as cli, patch("lab.install_quadra.time.sleep"), pytest.raises(
        InstallQuadraError, match="daemon quadra not running after no shutdown",
    ):
        enable_daemon("container", "ceos1-both", verbose=False)
    assert cli.call_count == 4
