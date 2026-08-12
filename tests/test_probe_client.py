"""Unit tests for lab.probe_client."""

from __future__ import annotations

import os
import subprocess
from unittest.mock import patch

import pytest

from lab.probe_client import (
    DEFAULT_PROBE_NODE,
    PROBE_HOST_MODE,
    PROBE_RADIUS_NODE,
    curl_eapi_command,
    curl_eapi_argv,
    gnmi_get_command,
    openssl_s_client_command,
    live_check_prefix,
    probe_ca_path,
    probe_client_mode,
    probe_container,
    probe_gnmi_cert_path,
    probe_node_name,
    run_curl_eapi,
)


def test_probe_client_mode_default() -> None:
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("PROBE_CLIENT", None)
        assert probe_client_mode() == DEFAULT_PROBE_NODE


@pytest.mark.parametrize(
    ("env_value", "expected"),
    [
        ("radius", PROBE_RADIUS_NODE),
        ("host", PROBE_HOST_MODE),
        ("test_runner", DEFAULT_PROBE_NODE),
    ],
)
def test_probe_client_mode_override(env_value: str, expected: str) -> None:
    with patch.dict(os.environ, {"PROBE_CLIENT": env_value}, clear=False):
        assert probe_client_mode() == expected


def test_probe_client_mode_invalid() -> None:
    with patch.dict(os.environ, {"PROBE_CLIENT": "invalid"}, clear=False):
        with pytest.raises(ValueError, match="unsupported PROBE_CLIENT"):
            probe_client_mode()


def test_probe_container_name() -> None:
    assert probe_container(clab_name="quantum-safe") == "arista-quantum-safe-test-runner"
    assert (
        probe_container(clab_name="quantum-safe", mode=PROBE_RADIUS_NODE)
        == "arista-quantum-safe-radius"
    )


def test_probe_node_name_host_raises() -> None:
    with pytest.raises(ValueError, match="host probe mode"):
        probe_node_name(PROBE_HOST_MODE)


def test_curl_eapi_command_uses_openssl_conf() -> None:
    command = curl_eapi_command(
        "https://172.20.127.11:443/command-api",
        '{"jsonrpc":"2.0"}',
        mode=DEFAULT_PROBE_NODE,
    )
    assert "OPENSSL_CONF=/etc/probe/openssl-pqc.cnf" in command
    assert "curl -sk --tlsv1.3" in command


def test_curl_eapi_command_radius_openssl_conf() -> None:
    command = curl_eapi_command(
        "https://172.20.127.11:443/command-api",
        "{}",
        mode=PROBE_RADIUS_NODE,
    )
    assert "OPENSSL_CONF=/etc/raddb/openssl-pqc.cnf" in command


def test_curl_eapi_argv_host() -> None:
    argv = curl_eapi_argv("https://172.20.127.11:443/command-api", "{}")
    assert argv[0] == "curl"
    assert "--tlsv1.3" in argv


def test_run_curl_eapi_host_mode() -> None:
    with patch.dict(os.environ, {"PROBE_CLIENT": "host"}, clear=False):
        with patch(
            "lab.probe_client.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout='{"modelName":"cEOSLab"}',
                stderr="",
            ),
        ) as run:
            result = run_curl_eapi(
                node="ceos1-both",
                switch_ip="172.20.127.11",
                payload="{}",
            )
    assert result.returncode == 0
    assert run.call_args.args[0][0] == "curl"


def test_run_curl_eapi_container_mode() -> None:
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("PROBE_CLIENT", None)
        with patch(
            "lab.probe_client.docker_exec_probe",
            return_value=subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout='{"modelName":"cEOSLab"}',
                stderr="",
            ),
        ) as docker_exec:
            result = run_curl_eapi(
                node="ceos1-both",
                switch_ip="172.20.127.11",
                payload="{}",
            )
    assert result.returncode == 0
    docker_exec.assert_called_once()
    command = docker_exec.call_args.args[0]
    assert "OPENSSL_CONF=/etc/probe/openssl-pqc.cnf" in command


def test_live_check_prefix_default() -> None:
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("PROBE_CLIENT", None)
        assert live_check_prefix() == "[live / test-runner]  "


def test_live_check_prefix_radius() -> None:
    assert live_check_prefix(PROBE_RADIUS_NODE) == "[live / radius]  "


def test_probe_gnmi_cert_path_test_runner() -> None:
    assert probe_gnmi_cert_path("ceos1-both", DEFAULT_PROBE_NODE) == (
        "/etc/probe/certs/ceos1-both-gnmi.pem"
    )


def test_openssl_s_client_command_pqc_groups() -> None:
    command = openssl_s_client_command(
        "172.20.127.53:6514",
        ca_file="/etc/probe/certs/ca.pem",
        groups="X25519MLKEM768",
        servername="syslog",
        mode=DEFAULT_PROBE_NODE,
    )
    assert "OPENSSL_CONF=/etc/probe/openssl-pqc.cnf" in command
    assert "-groups X25519MLKEM768" in command
    assert "-servername syslog" in command


def test_gnmi_get_command_tls13_only() -> None:
    command = gnmi_get_command(
        "172.20.127.11:6030",
        ca_file="/etc/probe/certs/radsec-ca.pem",
        cert_file="/etc/probe/certs/ceos1-both-client.pem",
        key_file="/etc/probe/certs/ceos1-both-client.key",
    )
    assert "gnmic -a '172.20.127.11:6030'" in command
    assert "--tls-min-version 1.3 --tls-max-version 1.3" in command
    assert "/system/config/hostname" in command
