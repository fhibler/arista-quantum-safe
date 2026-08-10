"""Generate ETSI QKD 014 mTLS material for the lab KME and RADIUS (SAE) client."""

from __future__ import annotations

import subprocess
from pathlib import Path

from lab.topology_contract import KME_A_ID, KME_B_ID, KME_SAE_ID

REPO_ROOT = Path(__file__).resolve().parents[1]

CA_SUBJECT = "/CN=qkd-macsec-radius-kme-ca/O=Lab/C=US"
CERT_DAYS = 825


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def _write_ext(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _issue_kme_cert(
    *,
    work: Path,
    ca_crt: Path,
    ca_key: Path,
    kme_id: str,
    kme_ip: str,
    dns_names: list[str],
    basename: str,
) -> tuple[Path, Path]:
    """Create a KME server key/cert pair signed by the lab CA."""
    kme_key = work / f"{basename}.key.pem"
    kme_csr = work / f"{basename}.csr"
    kme_crt = work / f"{basename}.crt.pem"

    _run(
        [
            "openssl",
            "req",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(kme_key),
            "-out",
            str(kme_csr),
            "-subj",
            f"/CN={kme_id}/O=KME/C=US",
        ]
    )
    san = ", ".join([f"IP:{kme_ip}"] + [f"DNS:{name}" for name in dns_names])
    kme_ext = work / f"{basename}.ext"
    _write_ext(
        kme_ext,
        [
            f"subjectAltName = {san}",
            "extendedKeyUsage = serverAuth,clientAuth",
            "keyUsage = digitalSignature,keyEncipherment",
        ],
    )
    _run(
        [
            "openssl",
            "x509",
            "-req",
            "-in",
            str(kme_csr),
            "-CA",
            str(ca_crt),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-out",
            str(kme_crt),
            "-days",
            str(CERT_DAYS),
            "-extfile",
            str(kme_ext),
        ]
    )
    return kme_key, kme_crt


def generate_kme_pki(
    *,
    repo_root: Path | None = None,
    kme_a_ip: str,
    kme_b_ip: str,
) -> Path:
    """Create CA, KME server, and RADIUS SAE client certs under lab/.gen/kme-pki/."""
    root = repo_root or REPO_ROOT
    out = root / "lab" / ".gen" / "kme-pki"
    work = out / ".work"
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    ca_key = work / "ca.key.pem"
    ca_crt = work / "ca.crt.pem"
    if not ca_crt.is_file():
        _run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(ca_key),
                "-out",
                str(ca_crt),
                "-days",
                str(CERT_DAYS),
                "-subj",
                CA_SUBJECT,
            ]
        )

    kme_a_key, kme_a_crt = _issue_kme_cert(
        work=work,
        ca_crt=ca_crt,
        ca_key=ca_key,
        kme_id=KME_A_ID,
        kme_ip=kme_a_ip,
        dns_names=["kme-a", "clab-qkd-macsec-radius-kme-a"],
        basename="kme-a",
    )
    kme_b_key, kme_b_crt = _issue_kme_cert(
        work=work,
        ca_crt=ca_crt,
        ca_key=ca_key,
        kme_id=KME_B_ID,
        kme_ip=kme_b_ip,
        dns_names=["kme-b", "clab-qkd-macsec-radius-kme-b"],
        basename="kme-b",
    )

    sae_key = work / "sae.key.pem"
    sae_csr = work / "sae.csr"
    sae_crt = work / "sae.crt.pem"
    if not sae_crt.is_file():
        _run(
            [
                "openssl",
                "req",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(sae_key),
                "-out",
                str(sae_csr),
                "-subj",
                f"/CN={KME_SAE_ID}/O=SAE/C=US",
            ]
        )
        sae_ext = work / "sae.ext"
        _write_ext(
            sae_ext,
            [
                f"subjectAltName = DNS:radius,DNS:clab-qkd-macsec-radius-radius",
                "extendedKeyUsage = clientAuth",
                "keyUsage = digitalSignature",
            ],
        )
        _run(
            [
                "openssl",
                "x509",
                "-req",
                "-in",
                str(sae_csr),
                "-CA",
                str(ca_crt),
                "-CAkey",
                str(ca_key),
                "-CAcreateserial",
                "-out",
                str(sae_crt),
                "-days",
                str(CERT_DAYS),
                "-extfile",
                str(sae_ext),
            ]
        )

    (out / "ca.crt.pem").write_bytes(ca_crt.read_bytes())
    (out / "kme-a.crt.pem").write_bytes(kme_a_crt.read_bytes())
    (out / "kme-a.key.pem").write_bytes(kme_a_key.read_bytes())
    (out / "kme-b.crt.pem").write_bytes(kme_b_crt.read_bytes())
    (out / "kme-b.key.pem").write_bytes(kme_b_key.read_bytes())
    (out / "sae.crt.pem").write_bytes(sae_crt.read_bytes())
    (out / "sae.key.pem").write_bytes(sae_key.read_bytes())

    return out
