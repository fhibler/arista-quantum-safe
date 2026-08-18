"""Live lab checks for alpine host data-plane routing (IPv4 + IPv6)."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from lab.report import (
    CheckStatus,
    align_right,
    bold,
    print_test_header,
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
)


class HostRoutingError(RuntimeError):
    """Raised when a host routing check fails."""


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


def _dual_family_cell(v4_ok: bool | None, v6_ok: bool | None) -> str:
    if v4_ok is None:
        return "—"
    v4_mark = status_marker(CheckStatus.OK if v4_ok else CheckStatus.FAIL)
    v6_mark = status_marker(CheckStatus.OK if v6_ok else CheckStatus.FAIL)
    return f"{v4_mark} {v6_mark}"


def format_host_connectivity_matrix(
    results_v4: dict[tuple[str, str], bool],
    results_v6: dict[tuple[str, str], bool],
) -> str:
    """Return an ASCII ping matrix for host-to-host data-plane reachability (IPv4 + IPv6)."""
    hosts = tuple(HOST_DATA_PLANE)
    ips_v4 = host_data_ips()
    ips_v6 = host_data_ips6()
    ok_cell = status_marker(CheckStatus.OK)
    fail_cell = status_marker(CheckStatus.FAIL)
    dual_cell = _dual_family_cell(True, True)
    cell_width = max(
        4,
        visible_len(ok_cell),
        visible_len(fail_cell),
        visible_len(dual_cell),
        len("—"),
        max(len(ip) for ip in ips_v4.values()),
        max(len(ip) for ip in ips_v6.values()),
    )
    label_width = max(len(host) for host in hosts) + 3
    cell_gap = 2

    lines = [
        bold("HOST ROUTING (data-plane ping matrix)"),
        "",
        f"{'':>{label_width}}" + "".join(f"{host:>{cell_width + cell_gap}}" for host in hosts),
        f"{'':>{label_width}}" + "".join(f"{ips_v4[host]:>{cell_width + cell_gap}}" for host in hosts),
        f"{'':>{label_width}}" + "".join(f"{ips_v6[host]:>{cell_width + cell_gap}}" for host in hosts),
        "",
    ]
    for src in hosts:
        row = f"{src} →".ljust(label_width)
        for dst in hosts:
            if src == dst:
                cell = "—"
            else:
                cell = _dual_family_cell(
                    results_v4.get((src, dst)),
                    results_v6.get((src, dst)),
                )
            row += align_right(cell, cell_width + cell_gap)
        lines.append(row)
    return "\n".join(lines)


def _ping_title(
    *,
    src_host: str,
    dst_host: str,
    family: str,
    src_ip: str,
    dst_ip: str,
) -> str:
    return f"ping {family_label(family)}  / {src_host} ({src_ip}) -> {dst_host} ({dst_ip})"


def _ping_host(
    *,
    src_host: str,
    dst_host: str,
    src_ip: str,
    target_ip: str,
    clab_name: str,
    verbose: bool,
    family: str = "",
) -> bool:
    title = _ping_title(
        src_host=src_host,
        dst_host=dst_host,
        family=family,
        src_ip=src_ip,
        dst_ip=target_ip,
    )
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
        from lab.test_lab import LabTestError, run_step

        try:
            run_step(title, argv, verbose=True)
            report_ok("[live]  ", title)
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
        report_check("[live]  ", f"{title} timed out", CheckStatus.FAIL)
        return False
    ok = result.returncode == 0
    if ok:
        report_ok("[live]  ", title)
    else:
        detail = result.stderr.strip() or result.stdout.strip()
        message = f"{title} failed (exit {result.returncode}){': ' + detail if detail else ''}"
        report_check("[live]  ", message, CheckStatus.FAIL)
    return ok


def run_hosts_check(*, clab_name: str, verbose: bool) -> None:
    if verbose:
        from lab.test_lab import section

        section("HOST ROUTING", verbose=verbose)
    print_test_header(
        "Host routing verification (data-plane ping matrix)",
        "  [live]  alpine host ping across all off-diagonal pairs (IPv4 + IPv6)",
    )
    results: dict[str, dict[tuple[str, str], bool]] = {
        IP_FAMILY_IPV4: {},
        IP_FAMILY_IPV6: {},
    }
    ips = host_data_ips()
    ips6 = host_data_ips6()
    for src_host, dst_host, targets in host_ping_groups():
        for family, target_ip in targets:
            src_ip = ips[src_host] if family == IP_FAMILY_IPV4 else ips6[src_host]
            ok = _ping_host(
                src_host=src_host,
                dst_host=dst_host,
                src_ip=src_ip,
                target_ip=target_ip,
                clab_name=clab_name,
                verbose=verbose,
                family=family,
            )
            results[family][(src_host, dst_host)] = ok

    print()
    print(format_host_connectivity_matrix(results[IP_FAMILY_IPV4], results[IP_FAMILY_IPV6]))
    print()

    failed = [
        f"{src} → {dst} ({family_label(family)})"
        for family in IP_FAMILIES
        for (src, dst), ok in results[family].items()
        if not ok
    ]
    if failed:
        raise HostRoutingError(f"host routing failed: {', '.join(failed)}")
    if not verbose:
        report_summary("HOSTS", "all data-plane ping pairs reachable (IPv4 and IPv6)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify alpine host data-plane routing.")
    parser.add_argument("--clab-name", default=LAB_NAME)
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Echo commands and print full output (also enabled by VERBOSE=1)",
    )
    args = parser.parse_args(argv)
    verbose = args.verbose or os.environ.get("VERBOSE") == "1"

    try:
        run_hosts_check(clab_name=args.clab_name, verbose=verbose)
    except HostRoutingError as exc:
        report_summary("HOSTS", str(exc), CheckStatus.FAIL, file=sys.stderr)
        print(file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
