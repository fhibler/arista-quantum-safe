"""Live lab checks for RadSec (FreeRADIUS collector + switch AAA + PQC TLS)."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from lab.report import CheckStatus, print_check_group, print_device, print_test_header, report_ok, report_summary
from lab.test_pqc_connections import (
    CEOS_NODES,
    PqcConnectionError,
    check_radsec_config,
    check_radius_config,
    lab_targets_for_subnet,
    probe_radsec_collector_tls,
    probe_radsec_from_switch,
)
from lab.topology_contract import IP_FAMILIES, IP_FAMILY_IPV4, IP_FAMILY_IPV6, LAB_NAME, family_label
from lab.verbose import verbose_enabled


def run_radsec_checks(
    *,
    clab_name: str,
    mgmt_subnet: str,
    skip_config: bool = False,
    verbose: bool | None = None,
) -> None:
    targets = lab_targets_for_subnet(clab_name=clab_name, mgmt_subnet=mgmt_subnet)
    radius_ip = targets.mgmt_ips["radius"]
    radius_ipv6 = targets.mgmt_ips6["radius"]

    print_test_header(
        "RadSec verification (TLS 1.3, PQC-hybrid only — no classical fallback)",
        "  [config] FreeRADIUS listener + OpenSSL groups; per-switch RADSEC ssl profile",
        "  [live]   MGMT ping + test aaa from each switch",
        "  [live / test-runner]  RadSec collector TLS handshake with switch client cert",
        "  grouped by check type; IPv4 and IPv6 under each",
    )

    print_device("radius")
    if not skip_config:
        check_radius_config(targets, verbose=verbose)

    for node in CEOS_NODES:
        print()
        print_device(node)
        container = targets.ceos_container(node)
        if not skip_config:
            check_radsec_config(targets, node, verbose=verbose)

        if not skip_config:
            print_check_group("Reachability")
            for family in IP_FAMILIES:
                addr = radius_ip if family == IP_FAMILY_IPV4 else radius_ipv6
                argv = ["docker", "exec", "-i", container, "Cli"]
                input_text = f"enable\nping vrf MGMT {addr} repeat 3\n"
                if verbose_enabled(verbose):
                    from lab.verbose import echo_command

                    echo_command(f"{node} ping radius {family}", argv)
                result = subprocess.run(argv, input=input_text, text=True, capture_output=True, check=False)
                if result.returncode != 0 or "0% packet loss" not in result.stdout:
                    detail = result.stderr.strip() or result.stdout.strip()
                    raise PqcConnectionError(
                        f"{node} ping radius {family_label(family)} ({addr}) failed"
                        + (f": {detail}" if detail else "")
                    )
                report_ok("[live]", f"{node} ping radius {family_label(family)} ({addr})")

        print_check_group("RadSec")
        for family in IP_FAMILIES:
            probe_radsec_collector_tls(targets, node, family=family, verbose=verbose)
            probe_radsec_from_switch(targets, node, family=family, verbose=verbose)

    print()
    report_summary(
        "RadSec",
        f"all {'live checks only' if skip_config else '[config] and [live] checks'} "
        "passed (reachability, collector TLS, AAA; IPv4 and IPv6)",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify live RadSec connectivity and PQC TLS.")
    parser.add_argument("--clab-name", default=LAB_NAME)
    parser.add_argument("--mgmt-subnet", default="172.20.127.0/24")
    parser.add_argument(
        "--skip-config",
        action="store_true",
        help="Skip EOS show-command config checks (live connections only)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Echo commands and print full output (also enabled by VERBOSE=1)",
    )
    args = parser.parse_args(argv)
    verbose = args.verbose or os.environ.get("VERBOSE") == "1"

    try:
        run_radsec_checks(
            clab_name=args.clab_name,
            mgmt_subnet=args.mgmt_subnet,
            skip_config=args.skip_config,
            verbose=verbose,
        )
    except (PqcConnectionError, subprocess.CalledProcessError) as exc:
        report_summary("RadSec", str(exc), CheckStatus.FAIL, file=sys.stderr)
        print(file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
