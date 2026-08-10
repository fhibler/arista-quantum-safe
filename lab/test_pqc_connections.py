"""Live lab checks for TLS 1.3 and PQC-hybrid connectivity (eAPI + RadSec + SSH)."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass

from lab.topology_contract import RADSEC_PORT, mgmt_ips_for_subnet
from lab.verbose import echo_command, echo_result, verbose_enabled

OPENSSL_PQC_CNF = "/etc/raddb/openssl-pqc.cnf"
RADSEC_CA_IN_RADIUS = "/etc/raddb/certs/radsec/ca.pem"
PQC_GROUP = "X25519MLKEM768"
SSH_PQC_KEX = "mlkem768x25519-sha256"
SSH_PQC_NETNS = "ns-MGMT"
SSH_PQC_USER = "admin"
CEOS_PEERS = {"ceos1": "ceos2", "ceos2": "ceos1"}


@dataclass(frozen=True)
class LabTargets:
    clab_name: str
    radius_ip: str
    ceos_ips: dict[str, str]

    @property
    def radius_container(self) -> str:
        return f"clab-{self.clab_name}-radius"

    def ceos_container(self, node: str) -> str:
        return f"clab-{self.clab_name}-{node}"


class PqcConnectionError(RuntimeError):
    """Raised when a live PQC connectivity check fails."""


def print_device(name: str) -> None:
    """Print a section header for a lab node."""
    print(f"=== {name} ===")


def report_config(detail: str) -> None:
    """Report a config check (EOS show commands, listener presence)."""
    print(f"  [config] {detail}")


def report_live(detail: str) -> None:
    """Report a live connectivity check (handshake, API call, AAA test)."""
    print(f"  [live]   {detail}")


def docker_exec(
    container: str,
    command: str,
    *,
    input_text: str = "",
    check: bool = True,
    verbose: bool | None = None,
    title: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a shell command inside a lab container."""
    show = verbose_enabled(verbose)
    argv = ["docker", "exec", "-i", container, "sh", "-c", command]
    if show:
        echo_command(title or f"docker exec {container}", argv, input_text=input_text)
    result = subprocess.run(
        argv,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if show:
        echo_result(result)
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise PqcConnectionError(f"{container}: {detail}")
    return result


def ceos_cli(container: str, commands: str, *, verbose: bool | None = None) -> str:
    """Run privileged EOS CLI commands."""
    show = verbose_enabled(verbose)
    argv = ["docker", "exec", "-i", container, "Cli"]
    if show:
        echo_command(f"Cli {container}", argv, input_text=commands)
    result = subprocess.run(
        argv,
        input=commands,
        text=True,
        capture_output=True,
        check=False,
    )
    if show:
        echo_result(result)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise PqcConnectionError(f"{container}: {detail}")
    return result.stdout


def assert_contains(text: str, needle: str, *, label: str) -> None:
    if needle not in text:
        raise PqcConnectionError(f"{label}: expected {needle!r} in output")


def tls13_handshake(output: str) -> bool:
    return "TLSv1.3" in output


def negotiated_pqc_group(output: str) -> bool:
    if PQC_GROUP in output:
        return True
    return bool(re.search(r"Negotiated TLS1\.3 group:.*MLKEM", output))


def openssl_s_client(
    radius_container: str,
    *,
    connect: str,
    ca_file: str,
    cert_file: str | None = None,
    key_file: str | None = None,
    use_pqc_conf: bool = True,
    verbose: bool | None = None,
) -> str:
    env = f"OPENSSL_CONF={OPENSSL_PQC_CNF} " if use_pqc_conf else ""
    cert_args = ""
    if cert_file and key_file:
        cert_args = f"-cert {cert_file} -key {key_file} "
    command = (
        f"{env}openssl s_client -connect {connect} -tls1_3 "
        f"-CAfile {ca_file} {cert_args}-brief </dev/null 2>&1"
    )
    # s_client may exit non-zero after a successful brief handshake; inspect output instead.
    result = docker_exec(radius_container, command, check=False, verbose=verbose, title=f"openssl s_client {connect}")
    output = result.stdout + result.stderr
    if not tls13_handshake(output):
        raise PqcConnectionError(f"TLS 1.3 handshake to {connect} failed:\n{output}")
    return output


def check_radius_config(targets: LabTargets, *, verbose: bool | None = None) -> None:
    output = docker_exec(
        targets.radius_container,
        "netstat -ltn",
        verbose=verbose,
        title=f"{targets.radius_container} netstat",
    ).stdout
    assert_contains(output, f":{RADSEC_PORT}", label="radius RadSec listener")
    groups = docker_exec(
        targets.radius_container,
        "openssl list -tls-groups",
        verbose=verbose,
        title=f"{targets.radius_container} openssl groups",
    ).stdout
    assert_contains(groups, PQC_GROUP, label="radius OpenSSL groups")
    report_config(f"RadSec listener :{RADSEC_PORT}")
    report_config(f"OpenSSL groups include {PQC_GROUP}")


def check_switch_ssl_profile(
    targets: LabTargets,
    node: str,
    profile: str,
    *,
    verbose: bool | None = None,
) -> None:
    container = targets.ceos_container(node)
    ceos_cli(container, f"enable\nshow management security ssl profile {profile}\n", verbose=verbose)
    detail = ceos_cli(
        container,
        f"enable\nshow management security ssl profile {profile} detail\n",
        verbose=verbose,
    )
    assert_contains(detail, "State: valid", label=f"{node} {profile} profile")
    assert_contains(detail, PQC_GROUP, label=f"{node} {profile} KEX groups")


def check_eapi_config(targets: LabTargets, node: str, *, verbose: bool | None = None) -> None:
    container = targets.ceos_container(node)
    check_switch_ssl_profile(targets, node, "EAPI", verbose=verbose)
    http = ceos_cli(container, "enable\nshow management api http-commands\n", verbose=verbose)
    assert_contains(http, "SSL Profile: EAPI", label=f"{node} eAPI binding")
    report_config(f"eAPI ssl profile EAPI valid ({PQC_GROUP}), HTTPS bound")


def check_ssh_pqc_config(targets: LabTargets, node: str, *, verbose: bool | None = None) -> None:
    container = targets.ceos_container(node)
    ssh_cfg = ceos_cli(container, "enable\nshow running-config section management ssh\n", verbose=verbose)
    assert_contains(ssh_cfg, SSH_PQC_KEX, label=f"{node} SSH PQC KEX")
    assert_contains(ssh_cfg, "aes256-gcm@openssh.com", label=f"{node} SSH PQC cipher")
    assert_contains(ssh_cfg, "vrf MGMT", label=f"{node} SSH vrf MGMT")
    mgmt_status = ceos_cli(container, "enable\nshow management ssh vrf MGMT\n", verbose=verbose)
    assert_contains(mgmt_status, "SSHD status for VRF MGMT: enabled", label=f"{node} SSH server in vrf MGMT")
    default_status = ceos_cli(container, "enable\nshow management ssh\n", verbose=verbose)
    assert_contains(default_status, "SSHD status for Default VRF: disabled", label=f"{node} SSH server on default VRF")
    report_config(f"SSH {SSH_PQC_KEX}, AEAD ciphers, vrf MGMT only (default VRF disabled)")


def check_radsec_config(targets: LabTargets, node: str, *, verbose: bool | None = None) -> None:
    container = targets.ceos_container(node)
    check_switch_ssl_profile(targets, node, "RADSEC", verbose=verbose)
    radius_cfg = ceos_cli(container, "enable\nshow running-config | section radius\n", verbose=verbose)
    assert_contains(radius_cfg, "tls ssl-profile RADSEC", label=f"{node} RadSec transport")
    report_config(f"RadSec ssl profile RADSEC valid ({PQC_GROUP}), tls ssl-profile RADSEC")


def probe_eapi_https(targets: LabTargets, node: str, *, verbose: bool | None = None) -> None:
    ip = targets.ceos_ips[node]
    output = openssl_s_client(
        targets.radius_container,
        connect=f"{ip}:443",
        ca_file=RADSEC_CA_IN_RADIUS,
        verbose=verbose,
    )
    group = PQC_GROUP if negotiated_pqc_group(output) else "classical fallback"
    report_live(f"eAPI HTTPS handshake (TLS 1.3, {group})")


def probe_eapi_jsonrpc(node: str, switch_ip: str, *, verbose: bool | None = None) -> None:
    payload = (
        '{"jsonrpc":"2.0","method":"runCmds",'
        '"params":{"version":1,"cmds":["show version"],"format":"json"},"id":1}'
    )
    argv = [
        "curl",
        "-sk",
        "--tlsv1.3",
        "--tls-max",
        "1.3",
        "-u",
        "admin:",
        f"https://{switch_ip}:443/command-api",
        "-H",
        "Content-Type: application/json",
        "-d",
        payload,
    ]
    show = verbose_enabled(verbose)
    if show:
        echo_command(f"{node} eAPI JSON-RPC", argv)
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if show:
        echo_result(result, format_json=True)
    body = result.stdout.strip()
    if result.returncode != 0 or not body:
        detail = result.stderr.strip() or body or f"curl exit {result.returncode}"
        raise PqcConnectionError(f"{node} eAPI JSON-RPC: {detail}")
    if "modelName" not in body and "version" not in body.lower():
        raise PqcConnectionError(f"{node} eAPI JSON-RPC: unexpected response: {body[:200]}")
    report_live("eAPI JSON-RPC command-api")


def negotiated_ssh_pqc_kex(output: str) -> bool:
    return f"kex: algorithm: {SSH_PQC_KEX}" in output


def probe_ssh_pqc(targets: LabTargets, node: str, peer: str, *, verbose: bool | None = None) -> None:
    """SSH from node to peer over VRF MGMT using the cEOS PQC netns."""
    container = targets.ceos_container(node)
    peer_ip = targets.ceos_ips[peer]
    command = (
        f"ip netns exec {SSH_PQC_NETNS} ssh -vvv "
        f"-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
        f"-o PubkeyAuthentication=no -o PreferredAuthentications=keyboard-interactive "
        f"-o KexAlgorithms={SSH_PQC_KEX} "
        f"{SSH_PQC_USER}@{peer_ip} 'show hostname' 2>&1"
    )
    result = docker_exec(
        container,
        command,
        check=False,
        verbose=verbose,
        title=f"{node} SSH to {peer}",
    )
    output = result.stdout + result.stderr
    if result.returncode != 0:
        detail = output.strip() or f"exit {result.returncode}"
        raise PqcConnectionError(f"{node} SSH to {peer} ({peer_ip}): {detail[-500:]}")
    if not negotiated_ssh_pqc_kex(output):
        raise PqcConnectionError(
            f"{node} SSH to {peer}: expected kex {SSH_PQC_KEX!r} in handshake output"
        )
    assert_contains(output, f"Hostname: {peer}", label=f"{node} SSH to {peer} hostname")
    report_live(f"SSH to {peer} ({SSH_PQC_KEX})")


def probe_radsec_from_switch(targets: LabTargets, node: str, *, verbose: bool | None = None) -> None:
    container = targets.ceos_container(node)
    output = ceos_cli(
        container,
        "enable\n"
        f"test aaa group RADIUS server {targets.radius_ip} tls port {RADSEC_PORT} vrf MGMT\n",
        verbose=verbose,
    )
    assert_contains(
        output,
        "successfully authenticated",
        label=f"{node} RadSec AAA test",
    )
    report_live(f"RadSec AAA via test aaa → radius:{RADSEC_PORT}")


def run_live_checks(
    *,
    clab_name: str,
    mgmt_subnet: str,
    skip_config: bool = False,
    verbose: bool | None = None,
) -> None:
    show = verbose_enabled(verbose)
    ips = mgmt_ips_for_subnet(mgmt_subnet)
    targets = LabTargets(
        clab_name=clab_name,
        radius_ip=ips["radius"],
        ceos_ips={"ceos1": ips["ceos1"], "ceos2": ips["ceos2"]},
    )

    print("PQC verification (TLS 1.3 + hybrid KEX)")
    print("  [config] EOS show commands / local listener checks")
    print("  [live]   TLS handshakes, eAPI JSON-RPC, RadSec AAA, SSH PQC KEX\n")

    print_device("radius")
    if not skip_config:
        check_radius_config(targets, verbose=verbose)

    for node in ("ceos1", "ceos2"):
        print()
        print_device(node)
        if not skip_config:
            check_eapi_config(targets, node, verbose=verbose)
            check_radsec_config(targets, node, verbose=verbose)
            check_ssh_pqc_config(targets, node, verbose=verbose)
        probe_eapi_https(targets, node, verbose=verbose)
        probe_eapi_jsonrpc(node, targets.ceos_ips[node], verbose=verbose)
        probe_radsec_from_switch(targets, node, verbose=verbose)
        probe_ssh_pqc(targets, node, CEOS_PEERS[node], verbose=verbose)

    print()
    scope = "live checks only" if skip_config else "[config] and [live] checks"
    print(f"PQC: OK — all {scope} passed (eAPI, RadSec, SSH; TLS 1.3)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify live eAPI and RadSec PQC connectivity.")
    parser.add_argument("--clab-name", default="qkd-macsec-radius")
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
        run_live_checks(
            clab_name=args.clab_name,
            mgmt_subnet=args.mgmt_subnet,
            skip_config=args.skip_config,
            verbose=verbose,
        )
    except (PqcConnectionError, subprocess.CalledProcessError) as exc:
        print(f"\nPQC: FAIL — {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
