"""Unit tests for KME curl helpers."""

from __future__ import annotations

from lab.kme_http import (
    CEOS_KME_CA_CERT,
    CEOS_KME_SAE_B_CERT,
    CEOS_KME_SAE_B_KEY,
    CEOS_KME_SAE_CERT,
    CEOS_KME_SAE_KEY,
    KME_CA_CERT_CONTAINER,
    ceos_kme_curl_exec_argv,
    kme_curl_argv,
)


def test_kme_curl_argv_strict_verifies_chain() -> None:
    argv = kme_curl_argv(
        url="https://10.0.0.51:8010/api/v1/keys/id/status",
        cert="/certs/sae.crt.pem",
        key="/certs/sae.key.pem",
    )
    assert "-sk" not in argv
    assert "--cacert" in argv
    assert KME_CA_CERT_CONTAINER in argv
    assert "--tlsv1.3" in argv


def test_kme_curl_argv_non_strict_skips_verification() -> None:
    argv = kme_curl_argv(
        url="https://example/status",
        cert="/certs/sae.crt.pem",
        key="/certs/sae.key.pem",
        strict=False,
    )
    assert "-sk" in argv
    assert "--cacert" not in argv


def test_ceos_kme_curl_exec_argv_uses_mgmt_netns_and_lab_ca() -> None:
    argv = ceos_kme_curl_exec_argv(
        "arista-quantum-safe-ceos1-both",
        url="https://10.0.0.51:8010/api/v1/keys/id/status",
        cert=CEOS_KME_SAE_CERT,
        key=CEOS_KME_SAE_KEY,
    )
    assert argv[:4] == ["docker", "exec", "arista-quantum-safe-ceos1-both", "ip"]
    assert "netns" in argv
    assert "ns-MGMT" in argv
    assert CEOS_KME_CA_CERT in argv
    assert CEOS_KME_SAE_B_CERT not in argv
    assert "-sk" not in argv


def test_ceos_kme_curl_exec_argv_supports_slave_sae_material() -> None:
    argv = ceos_kme_curl_exec_argv(
        "arista-quantum-safe-ceos3-qkd",
        url="https://10.0.0.52:8020/api/v1/keys/id/status",
        cert=CEOS_KME_SAE_B_CERT,
        key=CEOS_KME_SAE_B_KEY,
    )
    assert CEOS_KME_SAE_B_CERT in argv
    assert CEOS_KME_SAE_B_KEY in argv
