"""Tests for RadSec PKI generation."""

from pathlib import Path

import pytest

from lab.gen_pki import generate_radsec_pki
from lab.topology_contract import PKI_FILES, RADSEC_PORT


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_generate_radsec_pki_files(tmp_path: Path) -> None:
    out = generate_radsec_pki(
        repo_root=tmp_path,
        radius_ip="172.20.127.50",
        ceos_mgmt_ips={"ceos1": "172.20.127.11", "ceos2": "172.20.127.12"},
    )
    assert out == tmp_path / "lab" / ".gen" / "pki"
    for name in PKI_FILES:
        assert (out / name).is_file(), name
    server = (out / "server.pem").read_text(encoding="utf-8")
    assert "BEGIN CERTIFICATE" in server
    assert "BEGIN PRIVATE KEY" in server or "BEGIN RSA PRIVATE KEY" in server
    eapi = (out / "ceos1-eapi.pem").read_text(encoding="utf-8")
    assert "BEGIN CERTIFICATE" in eapi


def test_tls_site_contract(repo_root: Path) -> None:
    tls = (repo_root / "configs" / "radius" / "raddb" / "sites-available" / "tls").read_text(
        encoding="utf-8"
    )
    assert f"port = {RADSEC_PORT}" in tls
    assert 'tls_min_version = "1.3"' in tls
