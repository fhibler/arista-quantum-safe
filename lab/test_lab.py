"""Live lab acceptance checks with optional verbose command echo and formatted output."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from typing import Sequence

from lab.ceos_json import assert_json_contains as _json_contains
from lab.test_pqc_connections import PqcConnectionError, ceos_cli, ceos_show_json
from lab.topology_contract import (
    HOST_DATA_PLANE,
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

    json_checks = (
        ("ping radius (MGMT VRF)", f"ping vrf MGMT {radius_ip} repeat 3", "0"),
        ("ssl profile RADSEC", "show management security ssl profile RADSEC", "valid"),
        (
            "ssl profile RADSEC detail (PQC groups)",
            "show management security ssl profile RADSEC detail",
            "X25519MLKEM768",
        ),
    )
    text_checks = (
        ("RadSec client config", "show running-config | section radius", "tls ssl-profile RADSEC"),
        (
            "RadSec AAA test",
            f"test aaa group RADIUS server {radius_ip} tls port 2083 vrf MGMT",
            "successfully authenticated",
        ),
    )
    for node in ("ceos1-both", "ceos2-pqc", "ceos3-qkd"):
        container = container_name(node, lab_name=clab_name)
        for label, show_command, expect in json_checks:
            try:
                payload = ceos_show_json(container, show_command, verbose=verbose)
                _json_contains(payload, expect, label=f"{node} {label}")
            except PqcConnectionError as exc:
                raise LabTestError(str(exc)) from exc
        for label, command, expect in text_checks:
            result = run_step(
                f"{node} {label}",
                ["docker", "exec", "-i", container, "Cli"],
                input_text=f"enable\n{command}\n",
                verbose=verbose,
            )
            if expect not in result.stdout:
                raise LabTestError(f"{node} {label}: expected {expect!r}")

    if not verbose:
        print("RADIUS: OK")


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


def host_data_ips() -> dict[str, str]:
    """Return host name → data-plane IP (without prefix)."""
    return {host: spec["addr"].split("/")[0] for host, spec in HOST_DATA_PLANE.items()}


def host_ping_pairs() -> tuple[tuple[str, str, str], ...]:
    """Return (src_host, dst_host, dst_ip) for every off-diagonal pair."""
    ips = host_data_ips()
    hosts = tuple(HOST_DATA_PLANE)
    return tuple(
        (src, dst, ips[dst])
        for src in hosts
        for dst in hosts
        if src != dst
    )


def format_host_connectivity_matrix(results: dict[tuple[str, str], bool]) -> str:
    """Return an ASCII ping matrix for host-to-host data-plane reachability."""
    hosts = tuple(HOST_DATA_PLANE)
    ips = host_data_ips()
    cell_width = max(4, max(len(ip) for ip in ips.values()))
    label_width = max(len(host) for host in hosts) + 3

    lines = [
        "HOST ROUTING (data-plane ping matrix)",
        "",
        f"{'':>{label_width}}" + "".join(f"{host:>{cell_width + 2}}" for host in hosts),
        f"{'':>{label_width}}" + "".join(f"{ips[host]:>{cell_width + 2}}" for host in hosts),
        "",
    ]
    for src in hosts:
        row = f"{src} →".ljust(label_width)
        for dst in hosts:
            if src == dst:
                cell = "—"
            elif results.get((src, dst)):
                cell = "OK"
            else:
                cell = "FAIL"
            row += f"{cell:>{cell_width + 2}}"
        lines.append(row)
    return "\n".join(lines)


def _ping_host(
    *,
    src_host: str,
    dst_host: str,
    target_ip: str,
    clab_name: str,
    verbose: bool,
) -> bool:
    title = f"{src_host} ping {dst_host} ({target_ip})"
    argv = [
        "docker",
        "exec",
        container_name(src_host, lab_name=clab_name),
        "ping",
        "-c3",
        "-W2",
        target_ip,
    ]
    if verbose:
        try:
            run_step(title, argv, verbose=True)
            return True
        except LabTestError:
            return False

    try:
        result = subprocess.run(
            argv,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0


def run_hosts_check(*, clab_name: str, verbose: bool) -> None:
    section("HOST ROUTING", verbose=verbose)
    results: dict[tuple[str, str], bool] = {}
    for src_host, dst_host, target_ip in host_ping_pairs():
        results[(src_host, dst_host)] = _ping_host(
            src_host=src_host,
            dst_host=dst_host,
            target_ip=target_ip,
            clab_name=clab_name,
            verbose=verbose,
        )

    print(format_host_connectivity_matrix(results))

    failed = [f"{src} → {dst}" for (src, dst), ok in results.items() if not ok]
    if failed:
        raise LabTestError(f"host routing failed: {', '.join(failed)}")


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
            run_python_module(
                "KME",
                "lab.test_kme",
                "--clab-name",
                clab_name,
                "--mgmt-subnet",
                mgmt_subnet,
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
