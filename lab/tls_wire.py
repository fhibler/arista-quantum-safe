"""OpenSSL TLS wire probe helpers — parse and report negotiated KEX/ciphers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Literal

from lab.errors import PqcConnectionError
from lab.probe_client import run_openssl_s_client
from lab.report import CheckStatus
from lab.topology_contract import TLS_PQC_GROUP

CLASSICAL_PROBE_GROUP = "secp256r1"
TlsWirePolicy = Literal["strict", "warn"]


@dataclass(frozen=True)
class TlsWireResult:
    pqc_confirmed: bool
    tls13: bool
    kex_group: str | None
    cipher: str | None


def tls13_handshake(output: str) -> bool:
    return "TLSv1.3" in output


def negotiated_pqc_group(output: str) -> bool:
    if TLS_PQC_GROUP in output:
        return True
    return bool(re.search(r"Negotiated TLS1\.3 group:.*MLKEM", output))


def extract_negotiated_tls_group(output: str) -> str | None:
    match = re.search(r"Negotiated TLS1\.3 group:\s*(\S+)", output)
    if match:
        group = match.group(1)
        if group not in ("<NULL>", "(NONE)"):
            return group
    if "Peer Temp Key: ECDH, prime256v1" in output:
        return CLASSICAL_PROBE_GROUP
    if re.search(r"Peer Temp Key: ECDH, X25519\b", output):
        return "x25519"
    return None


def extract_negotiated_cipher(output: str) -> str | None:
    for pattern in (
        r"Cipher is (\S+)",
        r"New, TLSv1\.3, Cipher is (\S+)",
        r"Ciphersuite: (\S+)",
    ):
        match = re.search(pattern, output)
        if match:
            return match.group(1)
    return None


def parse_tls_wire_output(output: str) -> TlsWireResult:
    tls13 = tls13_handshake(output)
    kex_group = extract_negotiated_tls_group(output) if tls13 else None
    cipher = extract_negotiated_cipher(output) if tls13 else None
    pqc_confirmed = tls13 and negotiated_pqc_group(output)
    return TlsWireResult(
        pqc_confirmed=pqc_confirmed,
        tls13=tls13,
        kex_group=kex_group,
        cipher=cipher,
    )


def run_tls_wire_probe(
    *,
    connect: str,
    ca_file: str | None = None,
    cert_file: str | None = None,
    key_file: str | None = None,
    classical_group: str = CLASSICAL_PROBE_GROUP,
    clab_name: str,
    verbose: bool | None = None,
    servername: str | None = None,
    groups: str | None = None,
    use_pqc_conf: bool = True,
    classical_fallback: bool = True,
) -> TlsWireResult:
    """Probe TLS 1.3 wire negotiation (PQC-first, optional classical diagnostic)."""
    common = dict(
        connect=connect,
        ca_file=ca_file,
        cert_file=cert_file,
        key_file=key_file,
        clab_name=clab_name,
        verbose=verbose,
        servername=servername,
    )
    pqc_output = run_openssl_s_client(
        **common,
        groups=groups,
        use_pqc_conf=use_pqc_conf,
    )
    pqc_result = parse_tls_wire_output(pqc_output)
    if pqc_result.pqc_confirmed or not classical_fallback:
        return pqc_result
    if pqc_result.tls13:
        return pqc_result

    classical_output = run_openssl_s_client(
        **common,
        use_pqc_conf=False,
        groups=classical_group,
    )
    classical_result = parse_tls_wire_output(classical_output)
    if classical_result.tls13:
        return classical_result
    return pqc_result


def format_tls_wire_summary(result: TlsWireResult, *, port: int | None = None) -> str:
    if not result.tls13:
        if port is not None:
            return f"no TLS 1.3 handshake on :{port}"
        return "no TLS 1.3 handshake"
    parts = ["TLS 1.3"]
    if result.kex_group:
        parts.append(f"KEX {result.kex_group}")
    if result.cipher:
        parts.append(f"cipher {result.cipher}")
    summary = ", ".join(parts)
    if result.pqc_confirmed:
        return summary
    return f"not PQC-safe — {summary}"


def tls_wire_status(result: TlsWireResult, policy: TlsWirePolicy) -> CheckStatus:
    if result.pqc_confirmed:
        return CheckStatus.OK
    if policy == "warn":
        return CheckStatus.WARN
    return CheckStatus.FAIL


def rpc_tls_wire_suffix(result: TlsWireResult | None) -> str:
    if result is None:
        return "wire KEX not verified"
    if result.pqc_confirmed:
        kex = result.kex_group or TLS_PQC_GROUP
        parts = [f"wire KEX {kex}"]
    elif result.tls13:
        kex = result.kex_group or "unknown"
        parts = [f"not PQC-safe — wire KEX {kex}"]
    else:
        return "wire KEX not verified"
    if result.cipher:
        parts.append(f"cipher {result.cipher}")
    return ", ".join(parts)


def extract_ssh_kex(output: str) -> str | None:
    match = re.search(r"kex: algorithm:\s*(\S+)", output)
    return match.group(1) if match else None


def extract_ssh_cipher(output: str) -> str | None:
    match = re.search(r"cipher:\s*(\S+)", output)
    return match.group(1) if match else None


def format_ssh_wire_summary(kex: str | None, cipher: str | None, *, expected_kex: str) -> str:
    parts: list[str] = []
    if kex:
        parts.append(f"KEX {kex}")
    if cipher:
        parts.append(f"cipher {cipher}")
    summary = ", ".join(parts) if parts else "KEX/cipher not parsed"
    if kex == expected_kex:
        return summary
    return f"not PQC-safe — {summary}"


def report_tls_wire_probe(
    label: str,
    family: str,
    result: TlsWireResult,
    *,
    policy: TlsWirePolicy,
    report_fn: Callable[..., None],
    port: int | None = None,
    probe_client: bool = True,
    error_label: str | None = None,
) -> TlsWireResult:
    """Report a TLS wire probe; raise PqcConnectionError on strict failure."""
    summary = format_tls_wire_summary(result, port=port)
    status = tls_wire_status(result, policy)
    detail = f"{label} ({family}), {summary}"
    if status is CheckStatus.FAIL:
        raise PqcConnectionError(f"{error_label or label} ({family}): {summary}")
    report_fn(detail, status=status, probe_client=probe_client)
    return result
