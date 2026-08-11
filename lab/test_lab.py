"""Live lab acceptance checks with optional verbose command echo and formatted output."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from typing import Sequence

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
from lab.topology_contract import (
    CEOS_KME_NODES,
    KME_B_SAE_ID,
    KME_KEY_SIZE,
    KME_SAE_ID,
    LAB_NAME,
    container_name,
    mgmt_ips_for_subnet,
)

ALL_SECTIONS = ("inspect", "radius", "kme", "pqc", "macsec", "hosts")


class LabTestError(RuntimeError):
    """Raised when a lab check fails."""


def section(title: str, *, verbose: bool) -> None:
    if not verbose:
        return
    bar = "=" * 78
    print(f"\n{bar}\n  {title}\n{bar}")


def run_step(
    title: str,
    argv: Sequence[str],
    *,
    input_text: str = "",
    verbose: bool = False,
    timeout_sec: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command; when verbose, echo argv and print captured output."""
    if verbose:
        print(f"\n--- {title} ---")
        print(f"$ {shlex.join(argv)}")
        if input_text:
            print("--- stdin ---")
            print(input_text.rstrip())
            print("--- end stdin ---")

    try:
        result = subprocess.run(
            list(argv),
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        raise LabTestError(f"{title} timed out after {timeout_sec}s") from exc

    if verbose:
        if result.stdout:
            print("--- stdout ---")
            print(result.stdout.rstrip())
        if result.stderr:
            print("--- stderr ---")
            print(result.stderr.rstrip())
        print(f"--- exit {result.returncode} ---")

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise LabTestError(f"{title} failed (exit {result.returncode}){': ' + detail if detail else ''}")
    return result


def format_json(raw: str) -> str:
    try:
        return json.dumps(json.loads(raw), indent=2, sort_keys=True)
    except json.JSONDecodeError:
        return raw.rstrip()


def run_inspect(clab_topo_gen: str, *, verbose: bool) -> None:
    section("INSPECT", verbose=verbose)
    run_step("containerlab inspect", ["containerlab", "inspect", "-t", clab_topo_gen], verbose=verbose)


def run_radius_checks(*, clab_name: str, radius_ip: str, verbose: bool) -> None:
    section("RADIUS", verbose=verbose)
    radius_container = container_name("radius", lab_name=clab_name)
    listener = run_step(
        "RadSec listener",
        ["docker", "exec", radius_container, "netstat", "-ltn"],
        verbose=verbose,
    )
    if ":2083" not in listener.stdout:
        raise LabTestError("RadSec listener not found on port 2083")

    checks = (
        ("ping radius (MGMT VRF)", f"enable\nping vrf MGMT {radius_ip} repeat 3\n", "0% packet loss"),
        ("ssl profile RADSEC", "enable\nshow management security ssl profile RADSEC\n", "valid"),
        (
            "ssl profile RADSEC detail (PQC groups)",
            "enable\nshow management security ssl profile RADSEC detail\n",
            "X25519MLKEM768",
        ),
        ("RadSec client config", "enable\nshow running-config | section radius\n", "tls ssl-profile RADSEC"),
        (
            "RadSec AAA test",
            f"enable\ntest aaa group RADIUS server {radius_ip} tls port 2083 vrf MGMT\n",
            "successfully authenticated",
        ),
    )
    for node in ("ceos1-both", "ceos2-pqc", "ceos3-qkd"):
        container = container_name(node, lab_name=clab_name)
        for label, commands, expect in checks:
            result = run_step(
                f"{node} {label}",
                ["docker", "exec", "-i", container, "Cli"],
                input_text=commands,
                verbose=verbose,
            )
            if expect not in result.stdout:
                raise LabTestError(f"{node} {label}: expected {expect!r}")

    if not verbose:
        print("RADIUS: OK")


def run_kme_checks(*, clab_name: str, kme_a_ip: str, kme_b_ip: str, verbose: bool) -> None:
    section("KME", verbose=verbose)
    checks = (
        (
            "SAE status (kme-a)",
            container_name("kme-a", lab_name=clab_name),
            f"https://{kme_a_ip}:8010/api/v1/keys/{KME_SAE_ID}/status",
            "/certs/sae.crt.pem",
            "/certs/sae.key.pem",
            '"source_KME_ID"',
        ),
        (
            "kme-a → kme-b peer status",
            container_name("kme-a", lab_name=clab_name),
            f"https://{kme_b_ip}:8020/api/v1/kme/status",
            "/certs/kme-a.crt.pem",
            "/certs/kme-a.key.pem",
            '"KME_ID"',
        ),
        (
            "kme-b → kme-a peer status",
            container_name("kme-b", lab_name=clab_name),
            f"https://{kme_a_ip}:8010/api/v1/kme/status",
            "/certs/kme-b.crt.pem",
            "/certs/kme-b.key.pem",
            '"KME_ID"',
        ),
    )

    for title, container, url, cert, key, expect in checks:
        argv = ["docker", "exec", container, *kme_curl_argv(url=url, cert=cert, key=key)]
        result = run_step(
            title,
            argv,
            verbose=verbose,
            timeout_sec=DOCKER_EXEC_TIMEOUT_SEC,
        )
        if expect not in result.stdout:
            raise LabTestError(f"{title} missing expected field {expect}")
        if verbose:
            print("--- formatted JSON ---")
            print(format_json(result.stdout))

    if not verbose:
        print(f"KME SAE status OK (master SAE {KME_SAE_ID})")
        print("KME peer status OK (kme-a <-> kme-b)")

    kme_a_container = container_name("kme-a", lab_name=clab_name)
    enc_body = json.dumps({"number": 1, "size": KME_KEY_SIZE * 8})
    enc = run_step(
        "KME enc_keys (master SAE, AES-256)",
        [
            "docker",
            "exec",
            kme_a_container,
            *kme_curl_argv(
                url=f"https://{kme_a_ip}:8010/api/v1/keys/{KME_B_SAE_ID}/enc_keys",
                cert="/certs/sae.crt.pem",
                key="/certs/sae.key.pem",
                method="POST",
                body=enc_body,
            ),
        ],
        verbose=verbose,
        timeout_sec=DOCKER_EXEC_TIMEOUT_SEC,
    )
    enc_payload = json.loads(enc.stdout)
    keys = enc_payload.get("keys")
    if not isinstance(keys, list) or not keys:
        raise LabTestError(f"enc_keys missing keys[]: {enc_payload!r}")
    key_id = keys[0].get("key_ID")
    key_b64 = keys[0].get("key")
    if not isinstance(key_id, str) or not isinstance(key_b64, str):
        raise LabTestError(f"enc_keys missing key_ID/key: {enc_payload!r}")

    dec_body = json.dumps({"key_IDs": [{"key_ID": key_id}]})
    dec = run_step(
        "KME dec_keys (slave SAE, AES-256)",
        [
            "docker",
            "exec",
            kme_a_container,
            *kme_curl_argv(
                url=f"https://{kme_b_ip}:8020/api/v1/keys/{KME_SAE_ID}/dec_keys",
                cert="/certs/sae-b.crt.pem",
                key="/certs/sae-b.key.pem",
                ca_cert=KME_CA_CERT_CONTAINER,
                method="POST",
                body=dec_body,
            ),
        ],
        verbose=verbose,
        timeout_sec=DOCKER_EXEC_TIMEOUT_SEC,
    )
    dec_payload = json.loads(dec.stdout)
    dec_keys = dec_payload.get("keys")
    if not isinstance(dec_keys, list) or len(dec_keys) != 1:
        raise LabTestError(f"dec_keys expected one key: {dec_payload!r}")
    if dec_keys[0].get("key_ID") != key_id:
        raise LabTestError(f"dec_keys key_ID mismatch: {dec_payload!r}")
    if dec_keys[0].get("key") != key_b64:
        raise LabTestError("dec_keys material does not match enc_keys")

    if verbose:
        print("--- formatted JSON ---")
        print(format_json(json.dumps({"key_ID": key_id, "key_size": KME_KEY_SIZE})))
    if not verbose:
        print(f"KME enc/dec round-trip OK (key_ID {key_id}, {KME_KEY_SIZE} bytes)")

    ceos_kme_checks = (
        (
            "kme-a SAE status (TLS chain verify)",
            kme_a_ip,
            KME_SAE_ID,
            CEOS_KME_SAE_CERT,
            CEOS_KME_SAE_KEY,
            '"source_KME_ID"',
        ),
        (
            "kme-b slave SAE status (TLS chain verify)",
            kme_b_ip,
            KME_B_SAE_ID,
            CEOS_KME_SAE_B_CERT,
            CEOS_KME_SAE_B_KEY,
            '"stored_key_count"',
        ),
    )
    for node in sorted(CEOS_KME_NODES):
        container = container_name(node, lab_name=clab_name)
        for label, kme_ip, sae_id, cert, key, expect in ceos_kme_checks:
            port = 8010 if kme_ip == kme_a_ip else 8020
            url = f"https://{kme_ip}:{port}/api/v1/keys/{sae_id}/status"
            argv = ceos_kme_curl_exec_argv(container, url=url, cert=cert, key=key)
            result = run_step(
                f"{node} {label}",
                argv,
                verbose=verbose,
                timeout_sec=DOCKER_EXEC_TIMEOUT_SEC,
            )
            if expect not in result.stdout:
                raise LabTestError(f"{node} {label}: expected {expect!r}")
            if verbose:
                print("--- formatted JSON ---")
                print(format_json(result.stdout))

    if not verbose:
        print(
            f"KME TLS chain verified from {', '.join(sorted(CEOS_KME_NODES))} "
            f"(lab CA {CEOS_KME_CA_CERT})"
        )


def run_python_module(title: str, module: str, *args: str, verbose: bool = False) -> None:
    section(title.upper(), verbose=verbose)
    argv = [sys.executable, "-m", module, *args]
    if verbose:
        argv.append("--verbose")
        print(f"\n--- {title} ---")
        print(f"$ {shlex.join(argv)}")
    env = {**os.environ, "VERBOSE": "1"} if verbose else None
    result = subprocess.run(argv, check=False, env=env)
    if verbose:
        print(f"--- exit {result.returncode} ---")
    if result.returncode != 0:
        raise LabTestError(f"{title} failed (exit {result.returncode})")


def run_hosts_check(*, clab_name: str, verbose: bool) -> None:
    section("HOST ROUTING", verbose=verbose)
    checks = (
        ("host1 ping host2", container_name("host1", lab_name=clab_name), "10.0.2.1"),
        ("host1 ping host3", container_name("host1", lab_name=clab_name), "10.0.3.1"),
        ("host3 ping host1", container_name("host3", lab_name=clab_name), "10.0.1.1"),
    )
    for title, container, target in checks:
        run_step(
            title,
            ["docker", "exec", container, "ping", "-c3", target],
            verbose=verbose,
        )
    if not verbose:
        print("HOSTS: OK")


def run_sections(
    sections: Sequence[str],
    *,
    clab_name: str,
    clab_topo_gen: str,
    mgmt_subnet: str,
    verbose: bool,
) -> None:
    ips = mgmt_ips_for_subnet(mgmt_subnet)
    for name in sections:
        if name == "inspect":
            run_inspect(clab_topo_gen, verbose=verbose)
        elif name == "radius":
            run_radius_checks(clab_name=clab_name, radius_ip=ips["radius"], verbose=verbose)
        elif name == "kme":
            run_kme_checks(
                clab_name=clab_name,
                kme_a_ip=ips["kme-a"],
                kme_b_ip=ips["kme-b"],
                verbose=verbose,
            )
        elif name == "pqc":
            run_python_module(
                "PQC",
                "lab.test_pqc_connections",
                "--clab-name",
                clab_name,
                "--mgmt-subnet",
                mgmt_subnet,
                verbose=verbose,
            )
        elif name == "macsec":
            run_python_module(
                "MACsec",
                "lab.test_macsec",
                "--clab-name",
                clab_name,
                "--mgmt-subnet",
                mgmt_subnet,
                verbose=verbose,
            )
        elif name == "hosts":
            run_hosts_check(clab_name=clab_name, verbose=verbose)
        else:
            raise LabTestError(f"unknown section: {name}")

    if len(sections) > 1 and verbose:
        section("SUMMARY", verbose=True)
        print("All lab checks passed.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run live lab acceptance checks.")
    parser.add_argument("--clab-name", default=LAB_NAME)
    parser.add_argument(
        "--clab-topo-gen",
        default="lab/.gen.quantum-safe.clab.yml",
        help="Generated Containerlab topology file (inspect section only)",
    )
    parser.add_argument("--mgmt-subnet", default="172.20.127.0/24")
    parser.add_argument(
        "--section",
        action="append",
        dest="sections",
        choices=ALL_SECTIONS,
        help="Run one section (repeatable; default: all lab checks)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Echo commands and print full formatted output (also enabled by VERBOSE=1)",
    )
    args = parser.parse_args(argv)
    verbose = args.verbose or os.environ.get("VERBOSE") == "1"
    if args.sections:
        sections = args.sections
    elif verbose:
        sections = ALL_SECTIONS
    else:
        sections = ALL_SECTIONS[1:]

    try:
        run_sections(
            sections,
            clab_name=args.clab_name,
            clab_topo_gen=args.clab_topo_gen,
            mgmt_subnet=args.mgmt_subnet,
            verbose=verbose,
        )
    except (LabTestError, subprocess.CalledProcessError) as exc:
        print(f"\nLAB: FAIL — {exc}", file=sys.stderr)
        return 1

    if len(sections) > 1 and not verbose:
        print("All lab checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
