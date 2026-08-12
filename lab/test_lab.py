"""Live lab acceptance checks with optional verbose command echo and formatted output."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from typing import Sequence

from lab.test_pqc_connections import (
    PqcConnectionError,
    LabTargets,
    RADSEC_PORT,
    check_radsec_config,
    check_radius_config,
)
from lab.report import (
    CheckStatus,
    ICON_FAIL,
    ICON_OK,
    align_right,
    bold,
    print_device,
    print_section_header,
    report_check,
    report_ok,
    report_summary,
    status_marker,
    visible_len,
)
from lab.topology_contract import (
    HOST_DATA_PLANE,
    IP_FAMILIES,
    IP_FAMILY_IPV4,
    IP_FAMILY_IPV6,
    LAB_NAME,
    container_name,
    family_label,
    mgmt_ips_for_subnet,
    mgmt_ipv6_ips_for_subnet,
)

ALL_SECTIONS = ("inspect", "radius", "kme", "pqc", "macsec", "hosts")


class LabTestError(RuntimeError):
    """Raised when a lab check fails."""


def section(title: str, *, verbose: bool) -> None:
    if not verbose:
        return
    bar = "=" * 78
    print(f"\n{bar}")
    print(bold(f"  {title}"))
    print(bar)


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
        message = f"{title} failed (exit {result.returncode}){': ' + detail if detail else ''}"
        if not verbose:
            report_check("[live]", message, CheckStatus.FAIL)
        raise LabTestError(message)
    return result


def format_json(raw: str) -> str:
    try:
        return json.dumps(json.loads(raw), indent=2, sort_keys=True)
    except json.JSONDecodeError:
        return raw.rstrip()


def run_inspect(clab_topo_gen: str, *, verbose: bool) -> None:
    section("INSPECT", verbose=verbose)
    run_step("containerlab inspect", ["containerlab", "inspect", "-t", clab_topo_gen], verbose=verbose)


def run_radius_checks(
    *,
    clab_name: str,
    mgmt_ips: dict[str, str],
    mgmt_ips6: dict[str, str],
    verbose: bool,
) -> None:
    section("RADIUS", verbose=verbose)
    ceos_nodes = ("ceos1-both", "ceos2-pqc", "ceos3-qkd")
    targets = LabTargets(
        clab_name=clab_name,
        mgmt_ips=mgmt_ips,
        mgmt_ips6=mgmt_ips6,
        ceos_ips={node: mgmt_ips[node] for node in ceos_nodes},
        ceos_ips6={node: mgmt_ips6[node] for node in ceos_nodes},
    )
    radius_ip = mgmt_ips["radius"]
    radius_ipv6 = mgmt_ips6["radius"]

    print_device("radius")
    try:
        check_radius_config(targets, verbose=verbose)
    except PqcConnectionError as exc:
        raise LabTestError(str(exc)) from exc

    for node in ceos_nodes:
        container = targets.ceos_container(node)
        print_device(node)
        for family in IP_FAMILIES:
            addr = radius_ip if family == IP_FAMILY_IPV4 else radius_ipv6
            result = run_step(
                f"{node} ping radius {family} (MGMT VRF)",
                ["docker", "exec", "-i", container, "Cli"],
                input_text=f"enable\nping vrf MGMT {addr} repeat 3\n",
                verbose=verbose,
            )
            if "0% packet loss" not in result.stdout:
                raise LabTestError(
                    f"{node} ping radius {family} ({addr}): expected 0% packet loss"
                )
            report_ok("[live]", f"{node} ping radius {family} ({addr})")
        try:
            check_radsec_config(targets, node, verbose=verbose)
        except PqcConnectionError as exc:
            raise LabTestError(str(exc)) from exc
        for family in IP_FAMILIES:
            addr = radius_ip if family == IP_FAMILY_IPV4 else radius_ipv6
            result = run_step(
                f"{node} RadSec AAA test ({family})",
                ["docker", "exec", "-i", container, "Cli"],
                input_text=(
                    "enable\n"
                    f"test aaa group RADIUS server {addr} tls port {RADSEC_PORT} vrf MGMT\n"
                ),
                verbose=verbose,
            )
            if "successfully authenticated" not in result.stdout:
                raise LabTestError(
                    f"{node} RadSec AAA test ({family}): expected authentication success"
                )
            report_ok(
                "[live]",
                f"{node} RadSec AAA via test aaa ({family}) → radius:{RADSEC_PORT}",
            )

    if not verbose:
        report_summary("RADIUS", "all checks passed")


def run_python_module(title: str, module: str, *args: str, verbose: bool = False) -> None:
    section(title.upper(), verbose=verbose)
    argv = [sys.executable, "-m", module, *args]
    if verbose:
        argv.append("--verbose")
        print(f"\n--- {title} ---")
        print(f"$ {shlex.join(argv)}")
    env = {**os.environ, "VERBOSE": "1"} if verbose else {k: v for k, v in os.environ.items() if k != "VERBOSE"}
    result = subprocess.run(argv, check=False, env=env)
    if verbose:
        print(f"--- exit {result.returncode} ---")
    if result.returncode != 0:
        raise LabTestError(f"{title} failed (exit {result.returncode})")


def host_data_ips() -> dict[str, str]:
    """Return host name → data-plane IPv4 (without prefix)."""
    return {host: spec["addr"].split("/")[0] for host, spec in HOST_DATA_PLANE.items()}


def host_data_ips6() -> dict[str, str]:
    """Return host name → data-plane IPv6 (without prefix)."""
    return {host: spec["addr6"].split("/")[0] for host, spec in HOST_DATA_PLANE.items()}


def host_ping_groups() -> tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...]:
    """Return (src, dst, [(family, target_ip), ...]) for off-diagonal pairs."""
    ips = host_data_ips()
    ips6 = host_data_ips6()
    hosts = tuple(HOST_DATA_PLANE)
    groups: list[tuple[str, str, tuple[tuple[str, str], ...]]] = []
    for src in hosts:
        for dst in hosts:
            if src == dst:
                continue
            groups.append(
                (
                    src,
                    dst,
                    (
                        (IP_FAMILY_IPV4, ips[dst]),
                        (IP_FAMILY_IPV6, ips6[dst]),
                    ),
                )
            )
    return tuple(groups)


def format_host_connectivity_matrix(
    results: dict[tuple[str, str], bool],
    *,
    family: str,
) -> str:
    """Return an ASCII ping matrix for host-to-host data-plane reachability."""
    hosts = tuple(HOST_DATA_PLANE)
    ips = host_data_ips() if family == IP_FAMILY_IPV4 else host_data_ips6()
    ok_cell = status_marker(CheckStatus.OK)
    fail_cell = status_marker(CheckStatus.FAIL)
    cell_width = max(
        4,
        visible_len(ok_cell),
        visible_len(fail_cell),
        len("—"),
        max(len(ip) for ip in ips.values()),
    )
    label_width = max(len(host) for host in hosts) + 3
    cell_gap = 2

    lines = [
        bold(f"HOST ROUTING (data-plane ping matrix — {family_label(family)})"),
        "",
        f"{'':>{label_width}}" + "".join(f"{host:>{cell_width + cell_gap}}" for host in hosts),
        f"{'':>{label_width}}" + "".join(f"{ips[host]:>{cell_width + cell_gap}}" for host in hosts),
        "",
    ]
    for src in hosts:
        row = f"{src} →".ljust(label_width)
        for dst in hosts:
            if src == dst:
                cell = "—"
            elif results.get((src, dst)):
                cell = ok_cell
            else:
                cell = fail_cell
            row += align_right(cell, cell_width + cell_gap)
        lines.append(row)
    return "\n".join(lines)


def _ping_host(
    *,
    src_host: str,
    dst_host: str,
    target_ip: str,
    clab_name: str,
    verbose: bool,
    family: str = "",
) -> bool:
    family_suffix = f" {family_label(family)}" if family else ""
    title = f"{src_host} ping {dst_host}{family_suffix} ({target_ip})"
    argv = [
        "docker",
        "exec",
        container_name(src_host, lab_name=clab_name),
        "ping",
        "-c3",
        "-W2",
    ]
    if ":" in target_ip:
        argv.append("-6")
    argv.append(target_ip)
    if verbose:
        try:
            run_step(title, argv, verbose=True)
            report_ok("[live]", title)
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
        report_check("[live]", f"{title} timed out", CheckStatus.FAIL)
        return False
    ok = result.returncode == 0
    if ok:
        report_ok("[live]", title)
    else:
        detail = result.stderr.strip() or result.stdout.strip()
        message = f"{title} failed (exit {result.returncode}){': ' + detail if detail else ''}"
        report_check("[live]", message, CheckStatus.FAIL)
    return ok


def run_hosts_check(*, clab_name: str, verbose: bool) -> None:
    if verbose:
        section("HOST ROUTING", verbose=verbose)
    print_section_header("Host routing verification (data-plane ping matrix)")
    print("  [live]  alpine host ping across all off-diagonal pairs (IPv4 + IPv6)\n")
    results: dict[str, dict[tuple[str, str], bool]] = {
        IP_FAMILY_IPV4: {},
        IP_FAMILY_IPV6: {},
    }
    for src_host, dst_host, targets in host_ping_groups():
        for family, target_ip in targets:
            ok = _ping_host(
                src_host=src_host,
                dst_host=dst_host,
                target_ip=target_ip,
                clab_name=clab_name,
                verbose=verbose,
                family=family,
            )
            results[family][(src_host, dst_host)] = ok

    print(format_host_connectivity_matrix(results[IP_FAMILY_IPV4], family=IP_FAMILY_IPV4))
    print()
    print(format_host_connectivity_matrix(results[IP_FAMILY_IPV6], family=IP_FAMILY_IPV6))
    if not verbose:
        print()

    failed = [
        f"{src} → {dst} ({family_label(family)})"
        for family in IP_FAMILIES
        for (src, dst), ok in results[family].items()
        if not ok
    ]
    if failed:
        raise LabTestError(f"host routing failed: {', '.join(failed)}")
    if not verbose:
        report_summary("HOSTS", "all data-plane ping pairs reachable (IPv4 and IPv6)")


def run_sections(
    sections: Sequence[str],
    *,
    clab_name: str,
    clab_topo_gen: str,
    mgmt_subnet: str,
    verbose: bool,
) -> None:
    ips = mgmt_ips_for_subnet(mgmt_subnet)
    ips6 = mgmt_ipv6_ips_for_subnet()
    for index, name in enumerate(sections):
        if index > 0 and not verbose:
            print()
        if name == "inspect":
            run_inspect(clab_topo_gen, verbose=verbose)
        elif name == "radius":
            run_radius_checks(
                clab_name=clab_name,
                mgmt_ips=ips,
                mgmt_ips6=ips6,
                verbose=verbose,
            )
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
        report_summary("LAB", str(exc), CheckStatus.FAIL, file=sys.stderr)
        print(file=sys.stderr)
        return 1

    if len(sections) > 1 and not verbose:
        print()
        print(f"{ICON_OK} All lab checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
