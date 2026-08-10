"""Generate RadSec PKI material for the qkd-macsec-radius lab."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

CA_SUBJECT = "/CN=qkd-macsec-radius-radsec-ca/O=Lab/C=US"
CERT_DAYS = 825


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def _write_ext(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_radsec_pki(
    *,
    repo_root: Path | None = None,
    radius_ip: str,
    ceos_hosts: dict[str, str] | None = None,
) -> Path:
    """Create CA, server, and per-switch client certificates under lab/.gen/pki/."""
    root = repo_root or REPO_ROOT
    out = root / "lab" / ".gen" / "pki"
    work = out / ".work"
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    hosts = ceos_hosts or {"ceos1": "ceos1", "ceos2": "ceos2"}

    ca_key = work / "ca.key"
    ca_crt = work / "ca.crt"
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

    server_key = work / "server.key"
    server_csr = work / "server.csr"
    server_crt = work / "server.crt"
    if not server_crt.is_file():
        _run(
            [
                "openssl",
                "req",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(server_key),
                "-out",
                str(server_csr),
                "-subj",
                "/CN=radius/O=Lab/C=US",
            ]
        )
        server_ext = work / "server.ext"
        _write_ext(
            server_ext,
            [
                f"subjectAltName = IP:{radius_ip},DNS:radius,DNS:clab-qkd-macsec-radius-radius",
                "extendedKeyUsage = serverAuth",
                "keyUsage = digitalSignature,keyEncipherment",
            ],
        )
        _run(
            [
                "openssl",
                "x509",
                "-req",
                "-in",
                str(server_csr),
                "-CA",
                str(ca_crt),
                "-CAkey",
                str(ca_key),
                "-CAcreateserial",
                "-out",
                str(server_crt),
                "-days",
                str(CERT_DAYS),
                "-extfile",
                str(server_ext),
            ]
        )

    for name, cn in hosts.items():
        client_key = work / f"{name}-client.key"
        client_csr = work / f"{name}-client.csr"
        client_crt = work / f"{name}-client.crt"
        if client_crt.is_file():
            continue
        _run(
            [
                "openssl",
                "req",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(client_key),
                "-out",
                str(client_csr),
                "-subj",
                f"/CN={cn}/O=Lab/C=US",
            ]
        )
        client_ext = work / f"{name}-client.ext"
        _write_ext(
            client_ext,
            [
                f"subjectAltName = DNS:{cn}",
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
                str(client_csr),
                "-CA",
                str(ca_crt),
                "-CAkey",
                str(ca_key),
                "-CAcreateserial",
                "-out",
                str(client_crt),
                "-days",
                str(CERT_DAYS),
                "-extfile",
                str(client_ext),
            ]
        )

    (out / "ca.pem").write_bytes(ca_crt.read_bytes())
    (out / "radsec-ca.pem").write_bytes(ca_crt.read_bytes())
    (out / "server.pem").write_text(
        server_crt.read_text(encoding="utf-8") + server_key.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    for name in hosts:
        (out / f"{name}-client.pem").write_bytes((work / f"{name}-client.crt").read_bytes())
        (out / f"{name}-client.key").write_bytes((work / f"{name}-client.key").read_bytes())

    return out
