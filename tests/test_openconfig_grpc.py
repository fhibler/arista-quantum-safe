"""Unit tests for OpenConfig gRPC live check helpers."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from lab.test_openconfig_grpc import (
    gnpsi_supported_on_ceos,
    probe_gribi_mtls,
    probe_gribi_tls,
    probe_gnpsi_tls,
)
from lab.errors import PqcConnectionError
from lab.tls_wire import TlsWireResult, parse_tls_wire_output
from lab.topology_contract import GRIBI_PORT, GNPSI_PORT, TLS_PQC_GROUP


class _FakeTargets:
    clab_name = "quantum-safe"

    def ceos_container(self, node: str) -> str:
        return f"arista-quantum-safe-{node}"

    def ceos_mgmt_ip(self, node: str, family: str) -> str:
        return "172.20.127.11"


def test_gnpsi_supported_detects_invalid_command(monkeypatch) -> None:
    def fake_cli(container: str, commands: str, *, verbose=None) -> str:
        return "% Invalid input\n"

    monkeypatch.setattr("lab.test_pqc_connections.ceos_cli", fake_cli)
    assert gnpsi_supported_on_ceos(_FakeTargets(), "ceos1-both") is False


def test_gnpsi_supported_accepts_running_transport(monkeypatch) -> None:
    def fake_cli(container: str, commands: str, *, verbose=None) -> str:
        return "Enabled: Yes\nServer: running on port 6031, in MGMT VRF\n"

    monkeypatch.setattr("lab.test_pqc_connections.ceos_cli", fake_cli)
    assert gnpsi_supported_on_ceos(_FakeTargets(), "ceos1-both") is True


def _pqc_output() -> str:
    return (
        "CONNECTION ESTABLISHED\n"
        "Protocol version: TLSv1.3\n"
        f"Negotiated TLS1.3 group: {TLS_PQC_GROUP}\n"
        "Cipher is TLS_AES_256_GCM_SHA384\n"
    )


def _classical_output() -> str:
    return (
        "CONNECTION ESTABLISHED\n"
        "Protocol version: TLSv1.3\n"
        "Peer Temp Key: ECDH, prime256v1, 256 bits\n"
        "Cipher is TLS_AES_128_GCM_SHA256\n"
    )


def test_probe_gribi_tls_reports_pqc_kex_and_cipher(capsys) -> None:
    with patch("lab.test_openconfig_grpc.run_tls_wire_probe") as fake_probe:
        fake_probe.return_value = parse_tls_wire_output(_pqc_output())
        result = probe_gribi_tls(_FakeTargets(), "ceos1-both")

    assert result.pqc_confirmed is True
    output = capsys.readouterr().out
    assert f"KEX {TLS_PQC_GROUP}" in output
    assert "cipher TLS_AES_256_GCM_SHA384" in output


def test_probe_gribi_tls_warns_with_classical_kex_and_cipher(capsys) -> None:
    with patch("lab.test_openconfig_grpc.run_tls_wire_probe") as fake_probe:
        fake_probe.return_value = parse_tls_wire_output(_classical_output())
        result = probe_gribi_tls(_FakeTargets(), "ceos1-both")

    assert result.pqc_confirmed is False
    output = capsys.readouterr().out
    assert "WARN" in output
    assert "KEX secp256r1" in output
    assert "cipher TLS_AES_128_GCM_SHA256" in output


def test_probe_gribi_mtls_warns_when_tls_wire_classical(capsys) -> None:
    class _Result:
        returncode = 0
        stdout = "got 1 results\n"
        stderr = ""

    wire = parse_tls_wire_output(_classical_output())
    with patch("lab.test_openconfig_grpc.run_grpc_probe", return_value=_Result()):
        probe_gribi_mtls(_FakeTargets(), "ceos1-both", tls_wire=wire)

    output = capsys.readouterr().out
    assert "WARN" in output
    assert "wire KEX secp256r1" in output
    assert "cipher TLS_AES_128_GCM_SHA256" in output


def test_probe_gribi_mtls_raises_when_rpc_fails() -> None:
    class _Result:
        returncode = 1
        stdout = ""
        stderr = "rpc error"

    with patch("lab.test_openconfig_grpc.run_grpc_probe", return_value=_Result()):
        with pytest.raises(PqcConnectionError, match="gRIBI mTLS Get"):
            probe_gribi_mtls(_FakeTargets(), "ceos1-both", tls_wire=None)


def test_probe_gnpsi_tls_skips_on_connection_refused(capsys) -> None:
    empty = parse_tls_wire_output("connect: Connection refused\n")

    def fake_run(**kwargs):
        return empty

    with patch("lab.test_openconfig_grpc.run_tls_wire_probe", side_effect=fake_run):
        with patch(
            "lab.test_openconfig_grpc.run_openssl_s_client",
            return_value="connect: Connection refused\n",
        ):
            assert probe_gnpsi_tls(_FakeTargets(), "ceos1-both") is None

    output = capsys.readouterr().out
    assert "SKIP" in output
    assert str(GNPSI_PORT) in output
