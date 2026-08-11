"""Unit tests for live PQC connection check helpers."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from lab.topology_contract import GNMI_SSL_PROFILE, MGMT_IPV6_IPS, MGMT_IPS, RESTCONF_SSL_PROFILE, SYSLOG_SSL_PROFILE
from lab.test_pqc_connections import (
    PQC_GROUP,
    SSH_PQC_KEX,
    LabTargets,
    assert_contains,
    assert_pqc_hybrid_tls,
    negotiated_pqc_group,
    negotiated_ssh_pqc_kex,
    probe_eapi_https,
    probe_eapi_jsonrpc,
    probe_eossdkrpc_tls,
    probe_radsec_from_switch,
    probe_ssh_pqc,
    run_live_checks,
    tls13_handshake,
)
from lab.report import CheckStatus


def _ssl_profile_json() -> dict:
    return {
        "state": "valid",
        "tls13Groups": [PQC_GROUP],
        "trustedCertificates": ["radsec-ca.pem"],
    }


def _pqc_config_json() -> dict:
    return {
        "sslProfiles": [_ssl_profile_json()],
        "managementApi": {
            "httpCommands": {"sslProfile": "EAPI"},
            "gnmi": {"sslProfile": GNMI_SSL_PROFILE},
            "restconf": {"sslProfile": RESTCONF_SSL_PROFILE},
            "eosSdkRpc": {
                "enabled": True,
                "transports": {
                    "default": {
                        "enabled": True,
                        "sslProfile": GNMI_SSL_PROFILE,
                    }
                },
            },
        },
        "managementSsh": {
            "vrfMgmt": {"sshdStatus": "enabled"},
            "defaultVrf": {"sshdStatus": "disabled"},
            "keyExchange": SSH_PQC_KEX,
            "ciphers": ["aes256-gcm@openssh.com"],
            "vrf": "MGMT",
        },
        "radius": {"transport": "tls ssl-profile RADSEC"},
    }


def test_tls13_handshake_detects_tlsv13() -> None:
    assert tls13_handshake("Protocol version: TLSv1.3")
    assert not tls13_handshake("Protocol version: TLSv1.2")


def test_negotiated_pqc_group() -> None:
    assert negotiated_pqc_group(f"Negotiated TLS1.3 group: {PQC_GROUP}")
    assert not negotiated_pqc_group("Negotiated TLS1.3 group: ecdh_x25519")


def test_assert_pqc_hybrid_tls_rejects_classical() -> None:
    with pytest.raises(Exception, match="expected PQC-hybrid"):
        assert_pqc_hybrid_tls(
            "Protocol version: TLSv1.3\nNegotiated TLS1.3 group: secp256r1\n",
            label="probe",
        )


def test_negotiated_ssh_pqc_kex() -> None:
    assert negotiated_ssh_pqc_kex(f"debug1: kex: algorithm: {SSH_PQC_KEX}")
    assert not negotiated_ssh_pqc_kex("debug1: kex: algorithm: curve25519-sha256")


def test_assert_contains_raises_with_label() -> None:
    with pytest.raises(Exception, match="missing"):
        assert_contains("hello", "world", label="missing")


def _lab_targets(**overrides: object) -> LabTargets:
    defaults = {
        "clab_name": "quantum-safe",
        "mgmt_ips": dict(MGMT_IPS),
        "mgmt_ips6": dict(MGMT_IPV6_IPS),
        "ceos_ips": {
            "ceos1-both": MGMT_IPS["ceos1-both"],
            "ceos2-pqc": MGMT_IPS["ceos2-pqc"],
            "ceos3-qkd": MGMT_IPS["ceos3-qkd"],
        },
        "ceos_ips6": {
            "ceos1-both": MGMT_IPV6_IPS["ceos1-both"],
            "ceos2-pqc": MGMT_IPV6_IPS["ceos2-pqc"],
            "ceos3-qkd": MGMT_IPV6_IPS["ceos3-qkd"],
        },
    }
    defaults.update(overrides)
    return LabTargets(**defaults)  # type: ignore[arg-type]


def test_probe_eapi_jsonrpc_requires_version_payload(ip_family: str) -> None:
    switch_ip = MGMT_IPS["ceos1-both"] if ip_family == "ipv4" else MGMT_IPV6_IPS["ceos1-both"]
    with patch(
        "lab.test_pqc_connections.subprocess.run",
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout='{"modelName":"cEOSLab"}', stderr=""),
    ):
        probe_eapi_jsonrpc("ceos1-both", switch_ip, family=ip_family)

    with patch(
        "lab.test_pqc_connections.subprocess.run",
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="No authentication header found", stderr=""),
    ):
        with pytest.raises(Exception, match="unexpected response"):
            probe_eapi_jsonrpc("ceos1-both", switch_ip, family=ip_family)


def test_run_live_checks_happy_path(capsys) -> None:
    targets = _lab_targets()
    config_json = _pqc_config_json()
    syslog_host_line = (
        f"logging vrf MGMT host {MGMT_IPV6_IPS['syslog']} 6514 protocol tls ssl-profile SYSLOG"
    )

    def fake_docker_exec(container: str, command: str, *, input_text: str = "", check: bool = True, **kwargs: object):
        _ = check
        if "netstat -lun" in command:
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="udp 0.0.0.0:12345", stderr="")
        if "netstat -ltn" in command or "netstat" in command:
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="tcp 0.0.0.0:2083 tcp 0.0.0.0:6514", stderr="")
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
            peer = "ceos2-pqc" if MGMT_IPS["ceos2-pqc"] in command or MGMT_IPV6_IPS["ceos2-pqc"] in command else "ceos1-both"
            return subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=(
                    f"debug1: kex: algorithm: {SSH_PQC_KEX}\n"
                    f'{{"hostname":"{peer}"}}\n'
                ),
                stderr="",
            )
        if "test -f /tmp/cleartext-syslog-" in command:
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="no\n", stderr="")
        if "grep -F" in command and "quantum-safe-syslog-probe" in command:
            needle = command.split("'")[1]
            return subprocess.CompletedProcess(args=[], returncode=0, stdout=f"{needle}\n", stderr="")
        if "tcpdump" in command or "cleartext-syslog" in command:
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected docker exec: {container} {command!r}")

    def fake_ceos_cli(_container: str, commands: str, **kwargs: object) -> str:
        if "test aaa group RADIUS" in commands:
            return "successfully authenticated"
        if "show running-config | section eos-sdk-rpc" in commands:
            return "management api eos-sdk-rpc\n   transport grpc default\n      ssl profile GNMI\n"
        if "show running-config | section radius" in commands:
            return f"radius-server host {MGMT_IPV6_IPS['radius']} vrf MGMT tls ssl-profile RADSEC\n"
        if "show running-config section logging" in commands:
            return f"{syslog_host_line}\nlogging trap informational\n"
        if f"show management security ssl profile {SYSLOG_SSL_PROFILE} detail" in commands:
            return json.dumps({"state": "valid", "tls13Groups": [PQC_GROUP]})
        if "show running-config section management ssh" in commands:
            return (
                "management ssh\n"
                f"   key-exchange {SSH_PQC_KEX}\n"
                "   cipher aes256-gcm@openssh.com\n"
                "   vrf MGMT\n"
            )
        if "show management ssh vrf MGMT" in commands:
            return "SSHD status for VRF MGMT: enabled\n"
        if "show management ssh" in commands and "vrf MGMT" not in commands:
            return "SSHD status for Default VRF: disabled\n"
        if "send log level informational message" in commands:
            return ""
        if "| json" in commands:
            return json.dumps(config_json)
        raise AssertionError(f"unexpected ceos_cli commands: {commands!r}")

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
    assert "=== syslog ===" in output
    assert "--- Collector TLS ---" in output
    assert "=== ceos1-both ===" in output
    assert "=== ceos2-pqc ===" in output
    assert "=== ceos3-qkd ===" in output
    assert "--- eAPI ---" in output
    assert "--- SSH ---" in output
    assert "--- RadSec ---" in output
    assert "[config]" in output
    assert "[live]" in output
    assert "no cleartext syslog" in output
    assert "PQC: ✓" in output


def test_probe_ssh_pqc_requires_pqc_kex(ip_family: str) -> None:
    targets = _lab_targets()
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
            probe_ssh_pqc(targets, "ceos1-both", "ceos2-pqc", family=ip_family)


def test_probe_radsec_from_switch_requires_auth_success(ip_family: str) -> None:
    targets = _lab_targets()
    with patch(
        "lab.test_pqc_connections.ceos_cli",
        return_value="authentication failed",
    ):
        with pytest.raises(Exception, match="RadSec AAA test"):
            probe_radsec_from_switch(targets, "ceos1-both", family=ip_family)


def test_probe_eossdkrpc_tls_warns_when_pqc_handshake_fails(capsys) -> None:
    targets = _lab_targets()
    calls = {"n": 0}

    def fake_openssl(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return f"Connecting to {MGMT_IPS['ceos1-both']}\nunexpected eof while reading\n"
        return (
            "Protocol version: TLSv1.3\n"
            "Negotiated TLS1.3 group: secp256r1\n"
        )

    with patch("lab.test_pqc_connections.openssl_s_client", side_effect=fake_openssl):
        probe_eossdkrpc_tls(targets, "ceos1-both")

    output = capsys.readouterr().out
    assert "WARN" in output
    assert "secp256r1" in output


def test_probe_eapi_https_requires_tls13(ip_family: str) -> None:
    targets = _lab_targets()
    switch_ip = MGMT_IPS["ceos1-both"] if ip_family == "ipv4" else MGMT_IPV6_IPS["ceos1-both"]
    with patch(
        "lab.test_pqc_connections.openssl_s_client",
        side_effect=Exception(f"TLS 1.3 handshake to {switch_ip}:443 failed"),
    ):
        with pytest.raises(Exception):
            probe_eapi_https(targets, "ceos1-both", family=ip_family)
