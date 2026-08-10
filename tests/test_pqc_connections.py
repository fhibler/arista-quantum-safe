"""Unit tests for live PQC connection check helpers."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from lab.test_pqc_connections import (
    PQC_GROUP,
    SSH_PQC_KEX,
    LabTargets,
    assert_contains,
    negotiated_pqc_group,
    negotiated_ssh_pqc_kex,
    probe_eapi_https,
    probe_eapi_jsonrpc,
    probe_radsec_from_switch,
    probe_ssh_pqc,
    run_live_checks,
    tls13_handshake,
)


def test_tls13_handshake_detects_tlsv13() -> None:
    assert tls13_handshake("Protocol version: TLSv1.3")
    assert not tls13_handshake("Protocol version: TLSv1.2")


def test_negotiated_pqc_group() -> None:
    assert negotiated_pqc_group(f"Negotiated TLS1.3 group: {PQC_GROUP}")
    assert not negotiated_pqc_group("Negotiated TLS1.3 group: ecdh_x25519")


def test_negotiated_ssh_pqc_kex() -> None:
    assert negotiated_ssh_pqc_kex(f"debug1: kex: algorithm: {SSH_PQC_KEX}")
    assert not negotiated_ssh_pqc_kex("debug1: kex: algorithm: curve25519-sha256")


def test_assert_contains_raises_with_label() -> None:
    with pytest.raises(Exception, match="missing"):
        assert_contains("hello", "world", label="missing")


def test_probe_eapi_jsonrpc_requires_version_payload() -> None:
    with patch(
        "lab.test_pqc_connections.subprocess.run",
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout='{"modelName":"cEOSLab"}', stderr=""),
    ):
        probe_eapi_jsonrpc("ceos1", "172.20.127.11")

    with patch(
        "lab.test_pqc_connections.subprocess.run",
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="No authentication header found", stderr=""),
    ):
        with pytest.raises(Exception, match="unexpected response"):
            probe_eapi_jsonrpc("ceos1", "172.20.127.11")


def test_run_live_checks_happy_path(capsys) -> None:
    targets = LabTargets(
        clab_name="qkd-macsec-radius",
        radius_ip="172.20.127.50",
        ceos_ips={"ceos1": "172.20.127.11", "ceos2": "172.20.127.12"},
    )

    def fake_docker_exec(container: str, command: str, *, input_text: str = "", check: bool = True, **kwargs: object):
        _ = check
        if "netstat" in command:
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="tcp 0.0.0.0:2083", stderr="")
        if "openssl list -tls-groups" in command:
            return subprocess.CompletedProcess(args=[], returncode=0, stdout=PQC_GROUP, stderr="")
        if "openssl s_client" in command:
            return subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=f"CONNECTION ESTABLISHED\nProtocol version: TLSv1.3\nNegotiated TLS1.3 group: {PQC_GROUP}\n",
                stderr="",
            )
        if "ip netns exec" in command and "ssh" in command:
            peer = "ceos2" if "172.20.127.12" in command else "ceos1"
            return subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=(
                    f"debug1: kex: algorithm: {SSH_PQC_KEX}\n"
                    f"Hostname: {peer}\n"
                ),
                stderr="",
            )
        if command == "Cli":
            if "test aaa group RADIUS" in input_text:
                return subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout="successfully authenticated",
                    stderr="",
                )
            return subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=(
                    "State: valid\n"
                    "SSL Profile: EAPI\n"
                    f"TLS key establishment group(v1.3): {PQC_GROUP}:ecdh_x25519\n"
                    "tls ssl-profile RADSEC\n"
                    "key-exchange mlkem768x25519-sha256\n"
                    "aes256-gcm@openssh.com\n"
                    "vrf MGMT\n"
                    "no shutdown\n"
                    "SSHD status for VRF MGMT: enabled\n"
                    "SSHD status for Default VRF: disabled\n"
                ),
                stderr="",
            )
        raise AssertionError(f"unexpected docker exec: {container} {command!r}")

    def fake_ceos_cli(_container: str, commands: str, **kwargs: object) -> str:
        if "test aaa group RADIUS" in commands:
            return "successfully authenticated"
        return (
            "State: valid\n"
            "SSL Profile: EAPI\n"
            f"TLS key establishment group(v1.3): {PQC_GROUP}:ecdh_x25519\n"
            "tls ssl-profile RADSEC\n"
            "key-exchange mlkem768x25519-sha256\n"
            "aes256-gcm@openssh.com\n"
            "vrf MGMT\n"
            "no shutdown\n"
            "SSHD status for VRF MGMT: enabled\n"
            "SSHD status for Default VRF: disabled\n"
        )

    with (
        patch("lab.test_pqc_connections.docker_exec", side_effect=fake_docker_exec),
        patch("lab.test_pqc_connections.ceos_cli", side_effect=fake_ceos_cli),
        patch(
            "lab.test_pqc_connections.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout='{"modelName":"cEOSLab"}', stderr=""),
        ),
    ):
        run_live_checks(clab_name=targets.clab_name, mgmt_subnet="172.20.127.0/24")

    output = capsys.readouterr().out
    assert "=== radius ===" in output
    assert "=== ceos1 ===" in output
    assert "=== ceos2 ===" in output
    assert "[config]" in output
    assert "[live]" in output
    assert "PQC: OK" in output


def test_probe_ssh_pqc_requires_pqc_kex() -> None:
    targets = LabTargets(
        clab_name="qkd-macsec-radius",
        radius_ip="172.20.127.50",
        ceos_ips={"ceos1": "172.20.127.11", "ceos2": "172.20.127.12"},
    )
    with patch(
        "lab.test_pqc_connections.docker_exec",
        return_value=subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="debug1: kex: algorithm: curve25519-sha256\n",
            stderr="",
        ),
    ):
        with pytest.raises(Exception, match="expected kex"):
            probe_ssh_pqc(targets, "ceos1", "ceos2")


def test_probe_radsec_from_switch_requires_auth_success() -> None:
    targets = LabTargets(
        clab_name="qkd-macsec-radius",
        radius_ip="172.20.127.50",
        ceos_ips={"ceos1": "172.20.127.11", "ceos2": "172.20.127.12"},
    )
    with patch(
        "lab.test_pqc_connections.ceos_cli",
        return_value="authentication failed",
    ):
        with pytest.raises(Exception, match="RadSec AAA test"):
            probe_radsec_from_switch(targets, "ceos1")


def test_probe_eapi_https_requires_tls13() -> None:
    targets = LabTargets(
        clab_name="qkd-macsec-radius",
        radius_ip="172.20.127.50",
        ceos_ips={"ceos1": "172.20.127.11", "ceos2": "172.20.127.12"},
    )
    with patch(
        "lab.test_pqc_connections.openssl_s_client",
        side_effect=Exception("TLS 1.3 handshake to 172.20.127.11:443 failed"),
    ):
        with pytest.raises(Exception):
            probe_eapi_https(targets, "ceos1")
