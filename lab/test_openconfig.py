"""Live lab checks for OpenConfig gRPC services (gNMI, gNOI, gRIBI, gNSI, gNPSI, RESTCONF, eos-sdk-rpc)."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from lab.report import CheckStatus, print_check_group, print_device, print_section_header, report_summary
from lab.test_openconfig_grpc import run_openconfig_grpc_checks
from lab.test_pqc_connections import (
    CEOS_NODES,
    LabTargets,
    PqcConnectionError,
    check_eossdkrpc_config,
    check_gnmi_config,
    check_restconf_config,
    probe_eossdkrpc_tls,
    probe_gnmi_get,
    probe_gnmi_mtls,
    probe_gnmi_tls,
    probe_restconf_tls,
)
from lab.topology_contract import IP_FAMILIES, LAB_NAME, mgmt_ips_for_subnet, mgmt_ipv6_ips_for_subnet
from lab.verbose import verbose_enabled


def run_openconfig_checks(
    *,
    clab_name: str,
    mgmt_subnet: str,
    skip_config: bool = False,
    verbose: bool | None = None,
) -> None:
    ips = mgmt_ips_for_subnet(mgmt_subnet)
    ips6 = mgmt_ipv6_ips_for_subnet()
    targets = LabTargets(
        clab_name=clab_name,
        mgmt_ips=ips,
        mgmt_ips6=ips6,
        ceos_ips={"ceos1-both": ips["ceos1-both"], "ceos2-pqc": ips["ceos2-pqc"], "ceos3-qkd": ips["ceos3-qkd"]},
        ceos_ips6={"ceos1-both": ips6["ceos1-both"], "ceos2-pqc": ips6["ceos2-pqc"], "ceos3-qkd": ips6["ceos3-qkd"]},
    )

    print_section_header("OpenConfig verification (TLS 1.3, PQC-hybrid only — no classical fallback)")
    print("  [config] EOS show commands for gNMI, gRIBI, gNSI, gNPSI, RESTCONF, eos-sdk-rpc")
    print("  [live / test-runner]  gNMI/gNOI/gRIBI/gNSI/gNPSI gRPC, RESTCONF HTTPS, eos-sdk-rpc mTLS")
    print("  grouped by check type; IPv4 and IPv6 under each")

    for node in CEOS_NODES:
        print()
        print_device(node)
        if not skip_config:
            check_gnmi_config(targets, node, verbose=verbose)
            check_restconf_config(targets, node, verbose=verbose)
            check_eossdkrpc_config(targets, node, verbose=verbose)

        print_check_group("gNMI")
        for family in IP_FAMILIES:
            probe_gnmi_tls(targets, node, family=family, verbose=verbose)
            probe_gnmi_mtls(targets, node, family=family, verbose=verbose)
            probe_gnmi_get(targets, node, family=family, verbose=verbose)

        run_openconfig_grpc_checks(
            targets,
            (node,),
            skip_config=skip_config,
            verbose=verbose,
        )

        print_check_group("RESTCONF")
        for family in IP_FAMILIES:
            probe_restconf_tls(targets, node, family=family, verbose=verbose)

        print_check_group("eos-sdk-rpc")
        for family in IP_FAMILIES:
            probe_eossdkrpc_tls(targets, node, family=family, verbose=verbose)

    print()
    report_summary(
        "OpenConfig",
        f"all {'live checks only' if skip_config else '[config] and [live] checks'} "
        "passed (gNMI, gNOI, gRIBI, gNSI, gNPSI, RESTCONF, eos-sdk-rpc; "
        "WARN on eos-sdk-rpc not PQC-safe; SKIP on gNPSI subscribe / unsupported cEOS gNPSI)",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify live OpenConfig gRPC and RESTCONF PQC connectivity.")
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
        run_openconfig_checks(
            clab_name=args.clab_name,
            mgmt_subnet=args.mgmt_subnet,
            skip_config=args.skip_config,
            verbose=verbose,
        )
    except (PqcConnectionError, subprocess.CalledProcessError) as exc:
        report_summary("OpenConfig", str(exc), CheckStatus.FAIL, file=sys.stderr)
        print(file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
