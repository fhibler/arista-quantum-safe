"""Live lab checks for ETSI QKD 014 KME connectivity (per-KME and per-host)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass

from lab.kme_http import (
    CEOS_KME_CA_CERT,
    CEOS_KME_SAE_B_CERT,
    CEOS_KME_SAE_B_KEY,
    CEOS_KME_SAE_CERT,
    CEOS_KME_SAE_KEY,
    DOCKER_EXEC_TIMEOUT_SEC,
    KME_CA_CERT_CONTAINER,
    ceos_kme_curl_exec_argv,
    kme_curl_argv,
)
from lab.report import CheckStatus, print_device, print_test_header, report_ok, report_check_summary, report_summary, reset_check_stats
from lab.topology_contract import (
    CEOS_KME_NODES,
    KME_B_SAE_ID,
    KME_KEY_SIZE,
    KME_SAE_ID,
    LAB_NAME,
    container_name,
    mgmt_ips_for_subnet,
)
from lab.verbose import echo_command, echo_result, verbose_enabled


@dataclass(frozen=True)
class KmeTargets:
    clab_name: str
    kme_a_ip: str
    kme_b_ip: str

    def kme_container(self, node: str) -> str:
        return container_name(node, lab_name=self.clab_name)

    def ceos_container(self, node: str) -> str:
        return container_name(node, lab_name=self.clab_name)


class KmeCheckError(RuntimeError):
    """Raised when a live KME check fails."""


# KEY_GEN_SEC_TO_GEN=30 in topology; QuaDRA may drain the pool between deploy and test-kme.
ENC_KEYS_POOL_TIMEOUT_SEC = 35
ENC_KEYS_POOL_POLL_SEC = 5


def report_kme(detail: str) -> None:
    """Report a check executed inside a KME container."""
    report_ok("[kme] ", detail)


def report_host(detail: str) -> None:
    """Report a check executed from a cEOS host to a KME."""
    report_ok("[host]", detail)


def run_kme_curl(
    title: str,
    container: str,
    *,
    url: str,
    cert: str,
    key: str,
    ca_cert: str | None = None,
    method: str = "GET",
    body: str | None = None,
    verbose: bool | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run curl inside a KME container."""
    show = verbose_enabled(verbose)
    curl_kwargs: dict[str, str] = {
        "url": url,
        "cert": cert,
        "key": key,
        "method": method,
    }
    if ca_cert is not None:
        curl_kwargs["ca_cert"] = ca_cert
    if body is not None:
        curl_kwargs["body"] = body
    argv = ["docker", "exec", container, *kme_curl_argv(**curl_kwargs)]
    if show:
        echo_command(title, argv, input_text=body)
    try:
        result = subprocess.run(
            argv,
            text=True,
            capture_output=True,
            check=False,
            timeout=DOCKER_EXEC_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired as exc:
        raise KmeCheckError(f"{title} timed out after {DOCKER_EXEC_TIMEOUT_SEC}s") from exc
    if show:
        echo_result(result, format_json=True)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        if not detail and result.returncode == 22:
            detail = "HTTP error (empty key pool — try again later)"
        if not detail:
            detail = f"exit {result.returncode}"
        raise KmeCheckError(f"{title}: {detail}")
    return result


def run_ceos_kme_curl(
    title: str,
    container: str,
    *,
    url: str,
    cert: str,
    key: str,
    verbose: bool | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run strict-TLS curl from a cEOS node to a KME API endpoint."""
    show = verbose_enabled(verbose)
    argv = ceos_kme_curl_exec_argv(container, url=url, cert=cert, key=key)
    if show:
        echo_command(title, argv)
    try:
        result = subprocess.run(
            argv,
            text=True,
            capture_output=True,
            check=False,
            timeout=DOCKER_EXEC_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired as exc:
        raise KmeCheckError(f"{title} timed out after {DOCKER_EXEC_TIMEOUT_SEC}s") from exc
    if show:
        echo_result(result, format_json=True)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise KmeCheckError(f"{title}: {detail}")
    return result


def assert_contains(text: str, needle: str, *, label: str) -> None:
    if needle not in text:
        raise KmeCheckError(f"{label}: expected {needle!r}")


def check_kme_a_sae_status(targets: KmeTargets, *, verbose: bool | None = None) -> None:
    result = run_kme_curl(
        "kme-a SAE status",
        targets.kme_container("kme-a"),
        url=f"https://{targets.kme_a_ip}:8010/api/v1/keys/{KME_SAE_ID}/status",
        cert="/certs/sae.crt.pem",
        key="/certs/sae.key.pem",
        verbose=verbose,
    )
    assert_contains(result.stdout, '"source_KME_ID"', label="kme-a SAE status")
    report_kme(f"SAE status OK (master SAE {KME_SAE_ID})")


def check_kme_a_peer_status(targets: KmeTargets, *, verbose: bool | None = None) -> None:
    result = run_kme_curl(
        "kme-a → kme-b peer status",
        targets.kme_container("kme-a"),
        url=f"https://{targets.kme_b_ip}:8020/api/v1/kme/status",
        cert="/certs/kme-a.crt.pem",
        key="/certs/kme-a.key.pem",
        verbose=verbose,
    )
    assert_contains(result.stdout, '"KME_ID"', label="kme-a → kme-b peer status")
    report_kme("peer status OK (kme-a → kme-b)")


def check_kme_b_peer_status(targets: KmeTargets, *, verbose: bool | None = None) -> None:
    result = run_kme_curl(
        "kme-b → kme-a peer status",
        targets.kme_container("kme-b"),
        url=f"https://{targets.kme_a_ip}:8010/api/v1/kme/status",
        cert="/certs/kme-b.crt.pem",
        key="/certs/kme-b.key.pem",
        verbose=verbose,
    )
    assert_contains(result.stdout, '"KME_ID"', label="kme-b → kme-a peer status")
    report_kme("peer status OK (kme-b → kme-a)")


def _enc_keys_pool_empty(detail: str) -> bool:
    lowered = detail.lower()
    return "exit 22" in lowered or "empty key pool" in lowered or "try again later" in lowered


def enc_keys_on_kme_a(targets: KmeTargets, *, verbose: bool | None = None) -> tuple[str, str]:
    enc_body = json.dumps({"number": 1, "size": KME_KEY_SIZE * 8})
    title = "kme-a enc_keys (master SAE, AES-256)"
    url = f"https://{targets.kme_a_ip}:8010/api/v1/keys/{KME_B_SAE_ID}/enc_keys"
    deadline = time.monotonic() + ENC_KEYS_POOL_TIMEOUT_SEC

    while True:
        try:
            result = run_kme_curl(
                title,
                targets.kme_container("kme-a"),
                url=url,
                cert="/certs/sae.crt.pem",
                key="/certs/sae.key.pem",
                method="POST",
                body=enc_body,
                verbose=verbose,
            )
            enc_payload = json.loads(result.stdout)
            keys = enc_payload.get("keys")
            if not isinstance(keys, list) or not keys:
                raise KmeCheckError(f"enc_keys missing keys[]: {enc_payload!r}")
            key_id = keys[0].get("key_ID")
            key_b64 = keys[0].get("key")
            if not isinstance(key_id, str) or not isinstance(key_b64, str):
                raise KmeCheckError(f"enc_keys missing key_ID/key: {enc_payload!r}")
            report_kme(f"enc_keys OK (key_ID {key_id}, {KME_KEY_SIZE} bytes)")
            return key_id, key_b64
        except KmeCheckError as exc:
            if not _enc_keys_pool_empty(str(exc)) or time.monotonic() >= deadline:
                raise
            time.sleep(ENC_KEYS_POOL_POLL_SEC)


def dec_keys_on_kme_b(
    targets: KmeTargets,
    *,
    key_id: str,
    key_b64: str,
    verbose: bool | None = None,
) -> None:
    dec_body = json.dumps({"key_IDs": [{"key_ID": key_id}]})
    result = run_kme_curl(
        "kme-b dec_keys (slave SAE, AES-256)",
        targets.kme_container("kme-a"),
        url=f"https://{targets.kme_b_ip}:8020/api/v1/keys/{KME_SAE_ID}/dec_keys",
        cert="/certs/sae-b.crt.pem",
        key="/certs/sae-b.key.pem",
        ca_cert=KME_CA_CERT_CONTAINER,
        method="POST",
        body=dec_body,
        verbose=verbose,
    )
    dec_payload = json.loads(result.stdout)
    dec_keys = dec_payload.get("keys")
    if not isinstance(dec_keys, list) or len(dec_keys) != 1:
        raise KmeCheckError(f"dec_keys expected one key: {dec_payload!r}")
    if dec_keys[0].get("key_ID") != key_id:
        raise KmeCheckError(f"dec_keys key_ID mismatch: {dec_payload!r}")
    if dec_keys[0].get("key") != key_b64:
        raise KmeCheckError("dec_keys material does not match enc_keys")
    report_kme(f"dec_keys round-trip OK (key_ID {key_id})")


def check_ceos_host_kme_tls(
    targets: KmeTargets,
    node: str,
    *,
    verbose: bool | None = None,
) -> None:
    container = targets.ceos_container(node)
    host_checks = (
        (
            "kme-a SAE status (TLS chain verify)",
            targets.kme_a_ip,
            8010,
            KME_SAE_ID,
            CEOS_KME_SAE_CERT,
            CEOS_KME_SAE_KEY,
            '"source_KME_ID"',
        ),
        (
            "kme-b slave SAE status (TLS chain verify)",
            targets.kme_b_ip,
            8020,
            KME_B_SAE_ID,
            CEOS_KME_SAE_B_CERT,
            CEOS_KME_SAE_B_KEY,
            '"stored_key_count"',
        ),
    )
    for label, kme_ip, port, sae_id, cert, key, expect in host_checks:
        url = f"https://{kme_ip}:{port}/api/v1/keys/{sae_id}/status"
        result = run_ceos_kme_curl(
            f"{node} {label}",
            container,
            url=url,
            cert=cert,
            key=key,
            verbose=verbose,
        )
        assert_contains(result.stdout, expect, label=f"{node} {label}")
        report_host(label)


def run_kme_checks(
    *,
    clab_name: str,
    mgmt_subnet: str,
    kme_nodes: tuple[str, ...] = ("kme-a", "kme-b"),
    host_nodes: tuple[str, ...] | None = None,
    verbose: bool | None = None,
) -> None:
    reset_check_stats()
    ips = mgmt_ips_for_subnet(mgmt_subnet)
    targets = KmeTargets(
        clab_name=clab_name,
        kme_a_ip=ips["kme-a"],
        kme_b_ip=ips["kme-b"],
    )
    hosts = tuple(sorted(host_nodes if host_nodes is not None else CEOS_KME_NODES))

    print_test_header(
        "KME verification (ETSI QKD 014)",
        "  [kme]  SAE status, peer domain, enc/dec round-trip (inside KME containers)",
        "  [host] strict TLS chain verify from cEOS SAE clients",
    )

    key_id: str | None = None
    key_b64: str | None = None

    if "kme-a" in kme_nodes:
        print_device("kme-a")
        check_kme_a_sae_status(targets, verbose=verbose)
        check_kme_a_peer_status(targets, verbose=verbose)
        key_id, key_b64 = enc_keys_on_kme_a(targets, verbose=verbose)
        print()

    if "kme-b" in kme_nodes:
        print_device("kme-b")
        check_kme_b_peer_status(targets, verbose=verbose)
        if key_id is None or key_b64 is None:
            raise KmeCheckError("enc/dec round-trip requires kme-a checks (run both KME nodes)")
        dec_keys_on_kme_b(targets, key_id=key_id, key_b64=key_b64, verbose=verbose)
        print()

    for node in hosts:
        print_device(node)
        check_ceos_host_kme_tls(targets, node, verbose=verbose)
        print()

    report_check_summary("KME")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify live ETSI QKD 014 KME connectivity.")
    parser.add_argument("--clab-name", default=LAB_NAME)
    parser.add_argument("--mgmt-subnet", default="172.20.127.0/24")
    parser.add_argument(
        "--kme",
        action="append",
        dest="kme_nodes",
        choices=("kme-a", "kme-b"),
        help="Run checks for one KME node (repeatable; default: kme-a and kme-b)",
    )
    parser.add_argument(
        "--host",
        action="append",
        dest="host_nodes",
        choices=sorted(CEOS_KME_NODES),
        help="Run TLS checks from one cEOS host (repeatable; default: all KME SAE clients)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Echo commands and print full output (also enabled by VERBOSE=1)",
    )
    args = parser.parse_args(argv)
    verbose = args.verbose or os.environ.get("VERBOSE") == "1"

    kme_nodes = tuple(args.kme_nodes) if args.kme_nodes else ("kme-a", "kme-b")
    host_nodes = tuple(args.host_nodes) if args.host_nodes else None

    try:
        run_kme_checks(
            clab_name=args.clab_name,
            mgmt_subnet=args.mgmt_subnet,
            kme_nodes=kme_nodes,
            host_nodes=host_nodes,
            verbose=verbose,
        )
    except (KmeCheckError, subprocess.CalledProcessError) as exc:
        report_summary("KME", str(exc), CheckStatus.FAIL, file=sys.stderr)
        print(file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
