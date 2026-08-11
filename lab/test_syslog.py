"""Live lab checks for PQC-hybrid syslog-over-TLS from cEOS to syslog-ng."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from lab.syslog_checks import (
    PQC_GROUP,
    SyslogCheckError,
    CEOS_SYSLOG_NODES,
    check_switch_syslog_logging_config,
    check_switch_syslog_ssl_profile_detail,
    check_syslog_collector_listeners,
    probe_syslog_delivery_no_cleartext,
    probe_syslog_tls_pqc,
)
from lab.topology_contract import LAB_NAME, SYSLOG_SSL_PROFILE, container_name, mgmt_ips_for_subnet
from lab.verbose import echo_command, echo_result, verbose_enabled


def report_config(detail: str) -> None:
    print(f"  [config] {detail}")


def report_live(detail: str) -> None:
    print(f"  [live]   {detail}")


def docker_exec(
    container: str,
    command: str,
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    argv = ["docker", "exec", "-i", container, "sh", "-c", command]
    if verbose_enabled():
        echo_command(" ".join(argv))
    result = subprocess.run(argv, text=True, capture_output=True, check=False)
    if verbose_enabled():
        echo_result(result.stdout, result.stderr, result.returncode)
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise SyslogCheckError(f"{container}: {detail}")
    return result


def ceos_cli(node: str, clab_name: str, commands: str) -> str:
    container = container_name(node, lab_name=clab_name)
    result = docker_exec(container, f"{{ echo enable; {commands}; }} | Cli")
    return result.stdout


def print_device(name: str) -> None:
    print(f"=== {name} ===")


def run_checks(*, clab_name: str, mgmt_subnet: str, skip_live: bool = False) -> None:
    ips = mgmt_ips_for_subnet(mgmt_subnet)
    syslog_ip = ips["syslog"]
    syslog_container = container_name("syslog", lab_name=clab_name)

    print("Syslog verification (TLS 1.3 + hybrid KEX, no cleartext)")
    print(f"  collector: {syslog_ip}  profile: {SYSLOG_SSL_PROFILE}")

    if not skip_live:
        probe_syslog_tls_pqc(docker_exec, syslog_container=syslog_container, syslog_ip=syslog_ip)
        report_live(f"syslog-ng TLS handshake (TLS 1.3, {PQC_GROUP})")
    else:
        udp = docker_exec(syslog_container, "netstat -lun").stdout
        tcp = docker_exec(syslog_container, "netstat -ltn").stdout
        check_syslog_collector_listeners(udp, tcp)
        groups = docker_exec(syslog_container, "openssl list -tls-groups").stdout
        if PQC_GROUP not in groups:
            raise SyslogCheckError(f"syslog OpenSSL groups must include {PQC_GROUP!r}")
        report_config(f"collector TLS :6514 only, OpenSSL groups include {PQC_GROUP}")

    for node in CEOS_SYSLOG_NODES:
        print()
        print_device(node)
        logging_cfg = ceos_cli(node, clab_name, 'echo "show running-config section logging"')
        check_switch_syslog_logging_config(logging_cfg, node=node, syslog_ip=syslog_ip)
        report_config(f"no cleartext logging hosts, TLS host {syslog_ip}:6514")
        profile = ceos_cli(
            node,
            clab_name,
            f'echo "show management security ssl profile {SYSLOG_SSL_PROFILE} detail"',
        )
        check_switch_syslog_ssl_profile_detail(profile, node=node)
        report_config(f"ssl profile {SYSLOG_SSL_PROFILE} valid ({PQC_GROUP})")
        if skip_live:
            continue

        switch_ip = ips[node]
        needle = f"quantum-safe-syslog-probe-{node}"

        def send_log() -> None:
            ceos_cli(node, clab_name, f'echo "send log level informational message {needle}"')

        probe_syslog_delivery_no_cleartext(
            docker_exec,
            send_log,
            syslog_container=syslog_container,
            switch_ip=switch_ip,
            node=node,
        )
        report_live(f"{node} TLS syslog delivered, no cleartext packets from {switch_ip}")

    mode = "config checks only" if skip_live else "config and live delivery (no cleartext)"
    print(f"\nSyslog: OK — {mode} passed for all cEOS nodes")


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
        print(f"\nSyslog: FAIL — {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
