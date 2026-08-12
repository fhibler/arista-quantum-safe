"""Tests for RadSec PKI generation."""

from pathlib import Path

import pytest

from lab.gen_pki import generate_radsec_pki
from lab.topology_contract import MGMT_IPV6_IPS, PKI_FILES, RADSEC_PORT


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_generate_radsec_pki_files(tmp_path: Path, ip_family: str) -> None:
    radius_ip = (
        MGMT_IPV6_IPS["radius"] if ip_family == "ipv6" else "172.20.127.50"
    )
    syslog_ips = (
        (MGMT_IPV6_IPS["syslog"], "172.20.127.53")
        if ip_family == "ipv6"
        else ("172.20.127.53", MGMT_IPV6_IPS["syslog"])
    )
    out = generate_radsec_pki(
        repo_root=tmp_path,
        radius_ip=radius_ip,
        syslog_ips=syslog_ips,
        ceos_mgmt_ips={
            "ceos1-both": "172.20.127.11",
            "ceos2-pqc": "172.20.127.12",
            "ceos3-qkd": "172.20.127.13",
        },
        ceos_mgmt_ips6={
            "ceos1-both": MGMT_IPV6_IPS["ceos1-both"],
            "ceos2-pqc": MGMT_IPV6_IPS["ceos2-pqc"],
            "ceos3-qkd": MGMT_IPV6_IPS["ceos3-qkd"],
        },
    )
    assert out == tmp_path / "lab" / ".gen" / "pki"
    for name in PKI_FILES:
        assert (out / name).is_file(), name
    server = (out / "server.pem").read_text(encoding="utf-8")
    assert "BEGIN CERTIFICATE" in server
    assert "BEGIN PRIVATE KEY" in server or "BEGIN RSA PRIVATE KEY" in server
    eapi = (out / "ceos1-both-eapi.pem").read_text(encoding="utf-8")
    assert "BEGIN CERTIFICATE" in eapi


def test_ceos_server_certs_include_dual_stack_sans(tmp_path: Path) -> None:
    out = generate_radsec_pki(
        repo_root=tmp_path,
        radius_ip=MGMT_IPV6_IPS["radius"],
        ceos_mgmt_ips={"ceos1-both": "172.20.127.11"},
        ceos_mgmt_ips6={"ceos1-both": MGMT_IPV6_IPS["ceos1-both"]},
    )
    for role in ("eapi", "gnmi"):
        result = __import__("subprocess").run(
            ["openssl", "x509", "-in", str(out / f"ceos1-both-{role}.pem"), "-noout", "-text"],
            capture_output=True,
            text=True,
            check=True,
        )
        text = result.stdout
        assert "172.20.127.11" in text
        assert "2001:db8:127" in text.lower()


def test_tls_site_contract(repo_root: Path) -> None:
    tls = (repo_root / "configs" / "radius" / "raddb" / "sites-available" / "tls").read_text(
        encoding="utf-8"
    )
    assert f"port = {RADSEC_PORT}" in tls
    assert 'tls_min_version = "1.3"' in tls
