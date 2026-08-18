"""Live lab checks for PQC-hybrid syslog-over-TLS from cEOS to syslog-ng."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from lab.report import CheckStatus, print_check_group, print_device, print_test_header, report_ok, report_summary
from lab.syslog_checks import (
    PQC_GROUP,
    SyslogCheckError,
    CEOS_SYSLOG_NODES,
    check_switch_syslog_logging_config,
    check_switch_syslog_ssl_profile_detail,
    check_syslog_collector_listeners,
    wait_for_syslog_healthy,
)
from lab.test_pqc_connections import (
    PqcConnectionError,
    check_syslog_collector_config,
    lab_targets_for_subnet,
    probe_syslog_delivery,
    probe_syslog_tls,
)
from lab.topology_contract import (
    IP_FAMILIES,
    LAB_NAME,
    SYSLOG_SSL_PROFILE,
    container_name,
    mgmt_ips_for_subnet,
    mgmt_ipv6_ips_for_subnet,
)
from lab.verbose import echo_command, echo_result, verbose_enabled


def report_config(detail: str) -> None:
    report_ok("[config]", detail)


def docker_exec(
    container: str,
    command: str,
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    argv = ["docker", "exec", "-i", container, "sh", "-c", command]
    if verbose_enabled():
        echo_command(f"docker exec {container}", argv)
    result = subprocess.run(argv, text=True, capture_output=True, check=False)
    if verbose_enabled():
        echo_result(result)
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise SyslogCheckError(f"{container}: {detail}")
    return result


def ceos_cli(node: str, clab_name: str, commands: str) -> str:
    container = container_name(node, lab_name=clab_name)
    result = docker_exec(container, f"{{ echo enable; {commands}; }} | Cli")
    return result.stdout


def run_checks(*, clab_name: str, mgmt_subnet: str, skip_live: bool = False) -> None:
    ips = mgmt_ips_for_subnet(mgmt_subnet)
    ips6 = mgmt_ipv6_ips_for_subnet()
    syslog_ips = (ips["syslog"], ips6["syslog"])
    targets = lab_targets_for_subnet(clab_name=clab_name, mgmt_subnet=mgmt_subnet)

    print_test_header(
        "Syslog verification (TLS 1.3 + hybrid KEX, no cleartext)",
        f"  collector: {syslog_ips[0]} (IPv4), {syslog_ips[1]} (IPv6)  profile: {SYSLOG_SSL_PROFILE}",
        "  [live]   delivery + optional wire KEX capture (WARN when not PQC-safe)",
        "  grouped by check type; IPv4 and IPv6 under each",
    )

    print_device("syslog")
    if not skip_live:
        check_syslog_collector_config(targets, verbose=None)
        wait_for_syslog_healthy(targets.syslog_container)
        print_check_group("Collector TLS")
        for family in IP_FAMILIES:
            try:
                probe_syslog_tls(targets, family=family, verbose=None)
            except PqcConnectionError as exc:
                raise SyslogCheckError(str(exc)) from exc
    else:
        udp = docker_exec(targets.syslog_container, "netstat -lun").stdout
        tcp = docker_exec(targets.syslog_container, "netstat -ltn").stdout
        check_syslog_collector_listeners(udp, tcp)
        groups = docker_exec(targets.syslog_container, "openssl list -tls-groups").stdout
        if PQC_GROUP not in groups:
            raise SyslogCheckError(f"syslog OpenSSL groups must include {PQC_GROUP!r}")
        report_config(f"collector TLS :6514 only, OpenSSL groups include {PQC_GROUP}")

    for node in CEOS_SYSLOG_NODES:
        print()
        print_device(node)
        logging_cfg = ceos_cli(node, clab_name, 'echo "show running-config section logging"')
        check_switch_syslog_logging_config(logging_cfg, node=node, syslog_ips=syslog_ips)
        report_config(
            f"no cleartext logging hosts, TLS hosts {syslog_ips[0]}:6514, {syslog_ips[1]}:6514"
        )
        profile = ceos_cli(
            node,
            clab_name,
            f'echo "show management security ssl profile {SYSLOG_SSL_PROFILE} detail"',
        )
        check_switch_syslog_ssl_profile_detail(profile, node=node)
        report_config(f"ssl profile {SYSLOG_SSL_PROFILE} valid ({PQC_GROUP})")
        if skip_live:
            continue

        print_check_group("Delivery")
        for family in IP_FAMILIES:
            try:
                probe_syslog_delivery(targets, node, family=family, verbose=None)
            except PqcConnectionError as exc:
                raise SyslogCheckError(str(exc)) from exc

    mode = "config checks only" if skip_live else "config and live delivery (wire KEX WARN when not PQC-safe)"
    report_summary("Syslog", f"{mode} passed for all cEOS nodes")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify PQC-hybrid syslog from cEOS switches.")
    parser.add_argument("--clab-name", default=LAB_NAME)
    parser.add_argument("--mgmt-subnet", default=None)
    parser.add_argument("--skip-live", action="store_true", help="Config checks only.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    if args.verbose:
        os.environ["VERBOSE"] = "1"

    mgmt_subnet = args.mgmt_subnet
    if mgmt_subnet is None:
        from lab.topology_contract import DEFAULT_MGMT_SUBNET

        mgmt_subnet = DEFAULT_MGMT_SUBNET

    try:
        run_checks(clab_name=args.clab_name, mgmt_subnet=mgmt_subnet, skip_live=args.skip_live)
    except (SyslogCheckError, subprocess.CalledProcessError) as exc:
        report_summary("Syslog", str(exc), CheckStatus.FAIL, file=sys.stderr)
        print(file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
