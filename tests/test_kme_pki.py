"""Tests for KME mTLS PKI generation."""

from __future__ import annotations

import subprocess
from pathlib import Path

from lab.gen_kme_pki import generate_kme_pki
from lab.topology_contract import KME_PKI_FILES


def _openssl_text(path: Path) -> str:
    result = subprocess.run(
        ["openssl", "x509", "-in", str(path), "-noout", "-text"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_kme_ca_has_cert_sign_and_strict_verify(tmp_path: Path) -> None:
    out = generate_kme_pki(repo_root=tmp_path, kme_a_ip="172.20.127.51", kme_b_ip="172.20.127.52")
    assert out == tmp_path / "lab" / ".gen" / "kme-pki"
    for name in KME_PKI_FILES:
        assert (out / name).is_file(), name

    ca_text = _openssl_text(out / "ca.crt.pem")
    assert "CA:TRUE" in ca_text
    assert "Certificate Sign" in ca_text
    assert "CRL Sign" in ca_text

    for leaf in ("sae.crt.pem", "sae-b.crt.pem", "kme-a.crt.pem", "kme-b.crt.pem"):
        result = subprocess.run(
            ["openssl", "verify", "-x509_strict", "-CAfile", str(out / "ca.crt.pem"), str(out / leaf)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"{leaf}: {result.stderr or result.stdout}"


def test_kme_ca_without_key_usage_is_regenerated(tmp_path: Path) -> None:
    out = generate_kme_pki(repo_root=tmp_path, kme_a_ip="172.20.127.51", kme_b_ip="172.20.127.52")
    work = out / ".work"
    old_ca = (work / "ca.crt.pem").read_bytes()

    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(work / "ca.key.pem"),
            "-out",
            str(work / "ca.crt.pem"),
            "-days",
            "1",
            "-subj",
            "/CN=legacy-kme-ca",
        ],
        check=True,
        capture_output=True,
    )
    assert "Certificate Sign" not in _openssl_text(work / "ca.crt.pem")

    generate_kme_pki(repo_root=tmp_path, kme_a_ip="172.20.127.51", kme_b_ip="172.20.127.52")
    new_ca = (out / "ca.crt.pem").read_bytes()
    assert new_ca != old_ca
    assert "legacy-kme-ca" not in _openssl_text(out / "ca.crt.pem")
    assert "Certificate Sign" in _openssl_text(out / "ca.crt.pem")
    result = subprocess.run(
        [
            "openssl",
            "verify",
            "-x509_strict",
            "-CAfile",
            str(out / "ca.crt.pem"),
            str(out / "sae.crt.pem"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
