"""SSH probe helpers in lab.probe_client."""

from __future__ import annotations

import os
import subprocess
from unittest.mock import patch

import pytest

from lab.probe_client import (
    SSH_PQC_KEX,
    run_ssh_pqc_probe,
    ssh_pqc_command,
    ssh_probe_mode,
)


def test_ssh_probe_mode_defaults_to_test_runner() -> None:
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("PROBE_CLIENT", None)
        assert ssh_probe_mode() == "test-runner"


def test_ssh_probe_mode_honors_host_override() -> None:
    with patch.dict(os.environ, {"PROBE_CLIENT": "host"}, clear=False):
        assert ssh_probe_mode() == "host"


def test_ssh_probe_mode_ignores_radius_for_ssh() -> None:
    with patch.dict(os.environ, {"PROBE_CLIENT": "radius"}, clear=False):
        assert ssh_probe_mode() == "test-runner"


def test_ssh_pqc_command_includes_kex() -> None:
    command = ssh_pqc_command("172.20.127.11")
    assert f"KexAlgorithms={SSH_PQC_KEX}" in command
    assert "admin@172.20.127.11" in command


def test_run_ssh_pqc_probe_uses_test_runner() -> None:
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("PROBE_CLIENT", None)
        with patch(
            "lab.probe_client.docker_exec_probe",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr=""),
        ) as docker_exec:
            run_ssh_pqc_probe(node="ceos1-both", switch_ip="172.20.127.11")
    docker_exec.assert_called_once()
    assert f"KexAlgorithms={SSH_PQC_KEX}" in docker_exec.call_args.args[0]


def test_run_ssh_pqc_probe_host_mode() -> None:
    with patch.dict(os.environ, {"PROBE_CLIENT": "host"}, clear=False):
        with patch(
            "lab.probe_client.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr=""),
        ) as run:
            run_ssh_pqc_probe(node="ceos1-both", switch_ip="172.20.127.11")
    assert run.call_args.args[0][0] == "ssh"
