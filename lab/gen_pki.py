"""Generate RadSec PKI material for the Quantum Safe lab."""

from __future__ import annotations

import subprocess
from pathlib import Path

from lab.topology_contract import container_name

REPO_ROOT = Path(__file__).resolve().parents[1]

CA_SUBJECT = "/CN=quantum-safe-radsec-ca/O=Lab/C=US"
CERT_DAYS = 825


def _san_ip(ip: str) -> str:
    """Return an OpenSSL subjectAltName IP entry for IPv4 or IPv6."""
    return f"IP:{ip}"


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def _write_ext(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _generate_server_cert(
    *,
    work: Path,
    out: Path,
    name: str,
    role: str,
    mgmt_ip: str,
    ca_crt: Path,
    ca_key: Path,
) -> None:
    """Create or refresh a per-switch TLS server cert when the mgmt IP changes."""
    marker = work / f"{name}-{role}-san"
    server_key = work / f"{name}-{role}.key"
    server_csr = work / f"{name}-{role}.csr"
    server_crt = work / f"{name}-{role}.crt"
    if marker.is_file() and server_crt.is_file() and marker.read_text(encoding="utf-8").strip() == mgmt_ip:
        pass
    else:
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
                f"/CN={name}/O=Lab/C=US",
            ]
        )
        server_ext = work / f"{name}-{role}.ext"
        _write_ext(
            server_ext,
            [
                f"subjectAltName = {_san_ip(mgmt_ip)},DNS:{name},DNS:{container_name(name)}",
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
        marker.write_text(f"{mgmt_ip}\n", encoding="utf-8")

    (out / f"{name}-{role}.pem").write_bytes(server_crt.read_bytes())
    (out / f"{name}-{role}.key").write_bytes(server_key.read_bytes())


def _generate_syslog_server_cert(
    *,
    work: Path,
    out: Path,
    syslog_ip: str,
    ca_crt: Path,
    ca_key: Path,
) -> None:
    """Create or refresh the syslog collector TLS server cert when the mgmt IP changes."""
    marker = work / "syslog-server-san"
    server_key = work / "syslog-server.key"
    server_csr = work / "syslog-server.csr"
    server_crt = work / "syslog-server.crt"
    if marker.is_file() and server_crt.is_file() and marker.read_text(encoding="utf-8").strip() == syslog_ip:
        pass
    else:
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
                "/CN=syslog/O=Lab/C=US",
            ]
        )
        server_ext = work / "syslog-server.ext"
        _write_ext(
            server_ext,
            [
                f"subjectAltName = {_san_ip(syslog_ip)},DNS:syslog,DNS:{container_name('syslog')}",
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
        marker.write_text(f"{syslog_ip}\n", encoding="utf-8")

    (out / "syslog-server.pem").write_bytes(server_crt.read_bytes())
    (out / "syslog-server.key").write_bytes(server_key.read_bytes())


def generate_radsec_pki(
    *,
    repo_root: Path | None = None,
    radius_ip: str,
    syslog_ip: str | None = None,
    ceos_hosts: dict[str, str] | None = None,
    ceos_mgmt_ips: dict[str, str] | None = None,
) -> Path:
    """Create CA, server, and per-switch client/eAPI certificates under lab/.gen/pki/."""
    root = repo_root or REPO_ROOT
    out = root / "lab" / ".gen" / "pki"
    work = out / ".work"
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    hosts = ceos_hosts or (
        {name: name for name in ceos_mgmt_ips} if ceos_mgmt_ips else {"ceos1-both": "ceos1-both", "ceos2-pqc": "ceos2-pqc"}
    )

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
    server_marker = work / "server-san"
    if (
        server_marker.is_file()
        and server_crt.is_file()
        and server_marker.read_text(encoding="utf-8").strip() == radius_ip
    ):
        pass
    else:
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
                f"subjectAltName = {_san_ip(radius_ip)},DNS:radius,DNS:{container_name('radius')}",
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
        server_marker.write_text(f"{radius_ip}\n", encoding="utf-8")

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

    mgmt_ips = ceos_mgmt_ips or {}
    for name, mgmt_ip in mgmt_ips.items():
        for role in ("eapi", "gnmi"):
            _generate_server_cert(
                work=work,
                out=out,
                name=name,
                role=role,
                mgmt_ip=mgmt_ip,
                ca_crt=ca_crt,
                ca_key=ca_key,
            )

    if syslog_ip is not None:
        _generate_syslog_server_cert(
            work=work,
            out=out,
            syslog_ip=syslog_ip,
            ca_crt=ca_crt,
            ca_key=ca_key,
        )

    return out
