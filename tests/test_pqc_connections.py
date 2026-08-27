"""Unit tests for live PQC connection check helpers."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from lab.topology_contract import GNMI_SSL_PROFILE, MGMT_IPV6_IPS, MGMT_IPS, RESTCONF_SSL_PROFILE, SYSLOG_SSL_PROFILE
from lab.test_pqc_connections import (
    PQC_GROUP,
    SSH_PQC_CIPHERS,
    SSH_PQC_KEX,
    LabTargets,
    assert_contains,
    assert_pqc_hybrid_tls,
    check_ssh_pqc_config,
    negotiated_pqc_group,
    negotiated_ssh_pqc_kex,
    probe_eapi_https,
    probe_eapi_jsonrpc,
    probe_eossdkrpc_tls,
    probe_radsec_from_switch,
    probe_ssh_pqc,
    probe_syslog_delivery,
    run_eapi_checks,
    run_ssh_checks,
    tls13_handshake,
)
from lab.report import CheckStatus


def test_pqc_connection_error_lives_in_lab_errors() -> None:
    import inspect

    from lab import errors
    from lab.errors import PqcConnectionError

    assert inspect.getmodule(PqcConnectionError) is errors
    assert issubclass(PqcConnectionError, RuntimeError)


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
        "lab.test_pqc_connections.run_curl_eapi",
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout='{"modelName":"cEOSLab"}', stderr=""),
    ):
        probe_eapi_jsonrpc("ceos1-both", switch_ip, family=ip_family)

    with patch(
        "lab.test_pqc_connections.run_curl_eapi",
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="No authentication header found", stderr=""),
    ):
        with pytest.raises(Exception, match="unexpected response"):
            probe_eapi_jsonrpc("ceos1-both", switch_ip, family=ip_family)


def test_run_eapi_and_ssh_checks_happy_path(capsys) -> None:
    targets = _lab_targets()
    config_json = _pqc_config_json()

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
            raise AssertionError(f"unexpected ceos SSH loopback docker exec: {container} {command!r}")
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
        if "show running-config section logging" in commands:
            raise AssertionError(f"unexpected logging commands in eapi/ssh test: {commands!r}")
        if f"show management security ssl profile {SYSLOG_SSL_PROFILE} detail" in commands:
            raise AssertionError(f"unexpected syslog profile in eapi/ssh test: {commands!r}")
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

    def fake_run_ssh_pqc_probe(*, node: str, switch_ip: str, **kwargs: object):
        _ = kwargs
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                f"debug1: kex: algorithm: {SSH_PQC_KEX}\n"
                f"debug1: kex: server->client cipher: {SSH_PQC_CIPHERS} MAC: <implicit> compression: none\n"
                f'{{"hostname":"{node}"}}\n'
            ),
            stderr="",
        )

    def fake_openssl_s_client(**kwargs: object) -> str:
        return (
            f"CONNECTION ESTABLISHED\nProtocol version: TLSv1.3\n"
            f"Negotiated TLS1.3 group: {PQC_GROUP}\n"
        )

    with (
        patch("lab.test_pqc_connections.docker_exec", side_effect=fake_docker_exec),
        patch("lab.test_pqc_connections.ceos_cli", side_effect=fake_ceos_cli),
        patch(
            "lab.test_pqc_connections.run_curl_eapi",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout='{"modelName":"cEOSLab"}', stderr=""),
        ),
        patch(
            "lab.tls_wire.run_openssl_s_client",
            side_effect=fake_openssl_s_client,
        ),
        patch(
            "lab.test_pqc_connections.run_ssh_pqc_probe",
            side_effect=fake_run_ssh_pqc_probe,
        ),
    ):
        run_eapi_checks(clab_name=targets.clab_name, mgmt_subnet="172.20.127.0/24")
        run_ssh_checks(clab_name=targets.clab_name, mgmt_subnet="172.20.127.0/24")

    output = capsys.readouterr().out
    assert "=== ceos1-both ===" in output
    assert "=== ceos2-pqc ===" in output
    assert "=== ceos3-qkd ===" in output
    assert "--- eAPI ---" in output
    assert "--- SSH ---" in output
    assert "[config]" in output
    assert "[live / test-runner]" in output
    assert "eAPI: ✓" in output
    assert "SSH: ✓" in output


def test_probe_syslog_delivery_warns_on_classical_wire_kex(capsys) -> None:
    targets = _lab_targets()

    with (
        patch("lab.test_pqc_connections.probe_syslog_delivery_no_cleartext"),
        patch(
            "lab.test_pqc_connections.capture_eos_syslog_tls_key_share_group",
            return_value=29,
        ),
    ):
        probe_syslog_delivery(targets, "ceos2-pqc", family="ipv4")

    output = capsys.readouterr().out
    assert "WARN" in output
    assert "not PQC-safe" in output
    assert "TLS 1.3 compliant" in output
    assert "wire KEX x25519" in output
    assert "syslog client gap" not in output


def test_probe_syslog_delivery_warns_when_wire_kex_not_verified(capsys) -> None:
    targets = _lab_targets()

    with (
        patch("lab.test_pqc_connections.probe_syslog_delivery_no_cleartext"),
        patch(
            "lab.test_pqc_connections.capture_eos_syslog_tls_key_share_group",
            return_value=None,
        ),
    ):
        probe_syslog_delivery(targets, "ceos2-pqc", family="ipv4")

    output = capsys.readouterr().out
    assert "WARN" in output
    assert "not PQC-safe" in output
    assert "TLS 1.3 compliant" in output
    assert "wire KEX not verified" in output


def test_probe_ssh_pqc_requires_pqc_kex(ip_family: str) -> None:
    targets = _lab_targets()
    with patch(
        "lab.test_pqc_connections.run_ssh_pqc_probe",
        return_value=subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="debug1: kex: algorithm: curve25519-sha256\n",
            stderr="",
        ),
    ):
        with pytest.raises(Exception, match="expected kex"):
            probe_ssh_pqc(targets, "ceos1-both", family=ip_family)


def test_probe_ssh_pqc_requires_aes256_gcm(ip_family: str) -> None:
    targets = _lab_targets()
    with patch(
        "lab.test_pqc_connections.run_ssh_pqc_probe",
        return_value=subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                f"debug1: kex: algorithm: {SSH_PQC_KEX}\n"
                "debug1: kex: server->client cipher: chacha20-poly1305@openssh.com MAC: <implicit>\n"
                '{"hostname":"ceos1-both"}\n'
            ),
            stderr="",
        ),
    ):
        with pytest.raises(Exception, match="expected cipher"):
            probe_ssh_pqc(targets, "ceos1-both", family=ip_family)


def test_check_ssh_pqc_config_rejects_extra_ciphers() -> None:
    targets = _lab_targets()

    def fake_ceos_cli(_container: str, commands: str, **kwargs: object) -> str:
        if "show running-config section management ssh" in commands:
            return (
                "management ssh\n"
                f"   key-exchange {SSH_PQC_KEX}\n"
                "   cipher aes256-gcm@openssh.com aes128-gcm@openssh.com "
                "chacha20-poly1305@openssh.com\n"
                "   vrf MGMT\n"
            )
        if "show management ssh vrf MGMT" in commands:
            return "SSHD status for VRF MGMT: enabled\n"
        if "show management ssh" in commands:
            return "SSHD status for Default VRF: disabled\n"
        raise AssertionError(f"unexpected ceos_cli commands: {commands!r}")

    with patch("lab.test_pqc_connections.ceos_cli", side_effect=fake_ceos_cli):
        with pytest.raises(Exception, match="expected 'aes256-gcm@openssh.com' only"):
            check_ssh_pqc_config(targets, "ceos1-both")


def test_probe_radsec_from_switch_requires_auth_success(ip_family: str) -> None:
    targets = _lab_targets()
    with (
        patch(
            "lab.test_pqc_connections.ceos_cli",
            return_value="authentication failed",
        ),
        patch("lab.test_pqc_connections.time.sleep"),
    ):
        with pytest.raises(Exception, match="RadSec AAA test"):
            probe_radsec_from_switch(targets, "ceos1-both", family=ip_family)


def test_probe_radsec_from_switch_retries_until_auth_success(ip_family: str) -> None:
    targets = _lab_targets()
    call_count = {"n": 0}

    def fake_ceos_cli(_container: str, commands: str, **kwargs: object) -> str:
        assert "test aaa group RADIUS" in commands
        call_count["n"] += 1
        if call_count["n"] < 3:
            return "authentication failed"
        return "successfully authenticated"

    with patch("lab.test_pqc_connections.ceos_cli", side_effect=fake_ceos_cli):
        with patch("lab.test_pqc_connections.time.sleep") as sleep:
            probe_radsec_from_switch(targets, "ceos1-both", family=ip_family)

    assert call_count["n"] == 3
    assert sleep.call_count == 2


def test_probe_eossdkrpc_tls_skips_ipv6(capsys) -> None:
    targets = _lab_targets()

    with patch("lab.tls_wire.run_openssl_s_client") as fake_openssl:
        probe_eossdkrpc_tls(targets, "ceos1-both", family="ipv6")

    fake_openssl.assert_not_called()
    output = capsys.readouterr().out
    assert "SKIP" in output
    assert "IPv6" in output
    assert "local interface Management0 binds IPv4 only" in output


def test_probe_eossdkrpc_tls_warns_on_classical_secp256r1_probe(capsys) -> None:
    targets = _lab_targets()
    calls = {"n": 0}

    def fake_openssl(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return f"Connecting to {MGMT_IPS['ceos1-both']}\nunexpected eof while reading\n"
        return (
            "CONNECTION ESTABLISHED\n"
            "Protocol version: TLSv1.3\n"
            "Peer Temp Key: ECDH, prime256v1, 256 bits\n"
        )

    with patch("lab.tls_wire.run_openssl_s_client", side_effect=fake_openssl):
        probe_eossdkrpc_tls(targets, "ceos1-both")

    output = capsys.readouterr().out
    assert calls["n"] == 2
    assert "WARN" in output
    assert "not PQC-safe" in output
    assert "KEX secp256r1" in output


def test_probe_eossdkrpc_tls_warns_when_all_handshakes_fail(capsys) -> None:
    targets = _lab_targets()

    with patch(
        "lab.tls_wire.run_openssl_s_client",
        return_value="Connecting\nunexpected eof while reading\n",
    ):
        probe_eossdkrpc_tls(targets, "ceos1-both")

    output = capsys.readouterr().out
    assert "WARN" in output
    assert "no TLS 1.3 handshake on :9543" in output


def test_probe_eapi_https_requires_tls13(ip_family: str) -> None:
    targets = _lab_targets()
    switch_ip = MGMT_IPS["ceos1-both"] if ip_family == "ipv4" else MGMT_IPV6_IPS["ceos1-both"]
    with patch(
        "lab.test_pqc_connections.run_openssl_s_client",
        side_effect=Exception(f"TLS 1.3 handshake to {switch_ip}:443 failed"),
    ):
        with pytest.raises(Exception):
            probe_eapi_https(targets, "ceos1-both", family=ip_family)
