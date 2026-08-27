"""Unit tests for TLS wire probe helpers."""

from __future__ import annotations

from lab.report import CheckStatus
from lab.tls_wire import (
    CLASSICAL_PROBE_GROUP,
    extract_negotiated_cipher,
    extract_negotiated_tls_group,
    format_tls_wire_summary,
    parse_tls_wire_output,
    report_tls_wire_probe,
    rpc_tls_wire_suffix,
    run_tls_wire_probe,
)
from lab.topology_contract import TLS_PQC_GROUP


def test_parse_tls_wire_output_pqc_hybrid() -> None:
    output = (
        "CONNECTION ESTABLISHED\n"
        "Protocol version: TLSv1.3\n"
        f"Negotiated TLS1.3 group: {TLS_PQC_GROUP}\n"
        "New, TLSv1.3, Cipher is TLS_AES_256_GCM_SHA384\n"
    )
    result = parse_tls_wire_output(output)
    assert result.pqc_confirmed is True
    assert result.tls13 is True
    assert result.kex_group == TLS_PQC_GROUP
    assert result.cipher == "TLS_AES_256_GCM_SHA384"


def test_parse_tls_wire_output_classical() -> None:
    output = (
        "Protocol version: TLSv1.3\n"
        "Peer Temp Key: ECDH, prime256v1, 256 bits\n"
        "New, TLSv1.3, Cipher is TLS_AES_128_GCM_SHA256\n"
    )
    result = parse_tls_wire_output(output)
    assert result.pqc_confirmed is False
    assert result.kex_group == CLASSICAL_PROBE_GROUP
    assert result.cipher == "TLS_AES_128_GCM_SHA256"


def test_format_tls_wire_summary_includes_kex_and_cipher() -> None:
    result = parse_tls_wire_output(
        "Protocol version: TLSv1.3\n"
        f"Negotiated TLS1.3 group: {TLS_PQC_GROUP}\n"
        "Cipher is TLS_AES_256_GCM_SHA384\n"
    )
    summary = format_tls_wire_summary(result)
    assert f"KEX {TLS_PQC_GROUP}" in summary
    assert "cipher TLS_AES_256_GCM_SHA384" in summary


def test_rpc_tls_wire_suffix_warns_on_classical() -> None:
    result = parse_tls_wire_output(
        "Protocol version: TLSv1.3\n"
        "Peer Temp Key: ECDH, prime256v1, 256 bits\n"
        "Cipher is TLS_AES_128_GCM_SHA256\n"
    )
    suffix = rpc_tls_wire_suffix(result)
    assert "not PQC-safe" in suffix
    assert f"wire KEX {CLASSICAL_PROBE_GROUP}" in suffix
    assert "cipher TLS_AES_128_GCM_SHA256" in suffix


def test_extract_negotiated_cipher_from_brief_output() -> None:
    assert extract_negotiated_cipher("New, TLSv1.3, Cipher is TLS_CHACHA20_POLY1305_SHA256") == (
        "TLS_CHACHA20_POLY1305_SHA256"
    )
    assert extract_negotiated_cipher("Ciphersuite: TLS_AES_128_GCM_SHA256") == "TLS_AES_128_GCM_SHA256"


def test_extract_negotiated_tls_group_maps_prime256v1() -> None:
    output = "Protocol version: TLSv1.3\nPeer Temp Key: ECDH, prime256v1, 256 bits\n"
    assert extract_negotiated_tls_group(output) == CLASSICAL_PROBE_GROUP


def test_run_tls_wire_probe_returns_pqc_without_classical_fallback(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_s_client(**kwargs):
        calls.append(kwargs)
        return (
            "Protocol version: TLSv1.3\n"
            f"Negotiated TLS1.3 group: {TLS_PQC_GROUP}\n"
            "Cipher is TLS_AES_256_GCM_SHA384\n"
        )

    monkeypatch.setattr("lab.tls_wire.run_openssl_s_client", fake_s_client)
    result = run_tls_wire_probe(connect="172.20.127.11:443", clab_name="quantum-safe")
    assert result.pqc_confirmed is True
    assert len(calls) == 1
    assert calls[0].get("use_pqc_conf") is True


def test_run_tls_wire_probe_skips_fallback_when_tls13_classical(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_s_client(**kwargs):
        calls.append(kwargs)
        return (
            "Protocol version: TLSv1.3\n"
            "Peer Temp Key: ECDH, prime256v1, 256 bits\n"
            "Cipher is TLS_AES_128_GCM_SHA256\n"
        )

    monkeypatch.setattr("lab.tls_wire.run_openssl_s_client", fake_s_client)
    result = run_tls_wire_probe(connect="172.20.127.11:443", clab_name="quantum-safe")
    assert result.pqc_confirmed is False
    assert result.tls13 is True
    assert result.kex_group == CLASSICAL_PROBE_GROUP
    assert len(calls) == 1


def test_run_tls_wire_probe_classical_fallback_on_handshake_failure(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_s_client(**kwargs):
        calls.append(kwargs)
        if kwargs.get("use_pqc_conf") is False:
            return (
                "Protocol version: TLSv1.3\n"
                "Peer Temp Key: ECDH, prime256v1, 256 bits\n"
                "Cipher is TLS_AES_128_GCM_SHA256\n"
            )
        return "CONNECTED(00000003)\nunexpected eof while reading\n"

    monkeypatch.setattr("lab.tls_wire.run_openssl_s_client", fake_s_client)
    result = run_tls_wire_probe(connect="172.20.127.11:443", clab_name="quantum-safe")
    assert result.tls13 is True
    assert result.pqc_confirmed is False
    assert len(calls) == 2
    assert calls[1].get("use_pqc_conf") is False
    assert calls[1].get("groups") == CLASSICAL_PROBE_GROUP


def test_report_tls_wire_probe_warns_on_classical() -> None:
    reported: list[tuple[str, CheckStatus]] = []

    def report_fn(detail: str, *, status: CheckStatus, probe_client: bool = True) -> None:
        reported.append((detail, status))

    result = parse_tls_wire_output(
        "Protocol version: TLSv1.3\n"
        "Peer Temp Key: ECDH, prime256v1, 256 bits\n"
        "Cipher is TLS_AES_128_GCM_SHA256\n"
    )
    report_tls_wire_probe(
        "eAPI",
        "IPv4",
        result,
        policy="warn",
        report_fn=report_fn,
        port=443,
    )
    assert reported[0][1] is CheckStatus.WARN
