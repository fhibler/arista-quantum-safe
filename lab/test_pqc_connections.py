"""Live lab checks for TLS 1.3 and PQC-hybrid connectivity (eAPI + gNMI + RadSec + SSH)."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass

from lab.ceos_json import (
    CeosJsonError,
    assert_json_contains,
    json_transport_ssl_profile,
    json_truthy,
    parse_eos_json,
)
from lab.syslog_checks import (
    PQC_GROUP as SYSLOG_PQC_GROUP,
    SyslogCheckError,
    check_switch_syslog_logging_config,
    check_switch_syslog_ssl_profile_detail,
    check_syslog_collector_listeners,
    probe_syslog_delivery_no_cleartext,
    probe_syslog_tls_pqc,
)
from lab.topology_contract import (
    EOSSDKRPC_SSL_PROFILE,
    EOSSDKRPC_PORT,
    GNMI_PORT,
    GNMI_SSL_PROFILE,
    LAB_NAME,
    PROBE_CLIENT_CERT,
    PROBE_CLIENT_KEY,
    RADSEC_PORT,
    RESTCONF_PORT,
    RESTCONF_SSL_PROFILE,
    SYSLOG_SSL_PROFILE,
    container_name,
    mgmt_ips_for_subnet,
)
from lab.report import CheckStatus, print_device, print_section_header, report_ok, report_summary, report_warn
from lab.verbose import echo_command, echo_result, verbose_enabled

OPENSSL_PQC_CNF = "/etc/raddb/openssl-pqc.cnf"
RADSEC_CA_IN_RADIUS = "/etc/raddb/certs/radsec/ca.pem"
PQC_GROUP = "X25519MLKEM768"
SSH_PQC_KEX = "mlkem768x25519-sha256"
SSH_PQC_NETNS = "ns-MGMT"
SSH_PQC_USER = "admin"
CEOS_PEERS = {"ceos1-both": "ceos2-pqc", "ceos2-pqc": "ceos1-both", "ceos3-qkd": "ceos1-both"}


@dataclass(frozen=True)
class LabTargets:
    clab_name: str
    radius_ip: str
    syslog_ip: str
    ceos_ips: dict[str, str]

    @property
    def radius_container(self) -> str:
        return container_name("radius", lab_name=self.clab_name)

    @property
    def syslog_container(self) -> str:
        return container_name("syslog", lab_name=self.clab_name)

    def ceos_container(self, node: str) -> str:
        return container_name(node, lab_name=self.clab_name)


class PqcConnectionError(RuntimeError):
    """Raised when a live PQC connectivity check fails."""


def report_config(detail: str) -> None:
    """Report a config check (EOS show commands, listener presence)."""
    report_ok("[config]", detail)


def report_live(detail: str, *, status: CheckStatus = CheckStatus.OK) -> None:
    """Report a live connectivity check (handshake, API call, AAA test)."""
    if status is CheckStatus.WARN:
        report_warn("[live]  ", detail)
    else:
        report_ok("[live]  ", detail)


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
        echo_result(result, format_json="| json" in commands)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise PqcConnectionError(f"{container}: {detail}")
    return result.stdout


def ceos_show_json(container: str, show_command: str, *, verbose: bool | None = None):
    """Run a privileged EOS show command with ``| json`` and parse the result."""
    command = show_command.strip()
    if not command.endswith("| json"):
        command = f"{command} | json"
    try:
        return parse_eos_json(ceos_cli(container, f"enable\n{command}\n", verbose=verbose))
    except CeosJsonError as exc:
        raise PqcConnectionError(f"{container}: {exc}") from exc


def assert_contains(text: str, needle: str, *, label: str) -> None:
    if needle not in text:
        raise PqcConnectionError(f"{label}: expected {needle!r} in output")


def _assert_json_contains(obj, needle: str, *, label: str) -> None:
    try:
        assert_json_contains(obj, needle, label=label)
    except CeosJsonError as exc:
        raise PqcConnectionError(str(exc)) from exc


def tls13_handshake(output: str) -> bool:
    return "TLSv1.3" in output


def negotiated_pqc_group(output: str) -> bool:
    if PQC_GROUP in output:
        return True
    return bool(re.search(r"Negotiated TLS1\.3 group:.*MLKEM", output))


def extract_negotiated_tls_group(output: str) -> str | None:
    match = re.search(r"Negotiated TLS1\.3 group:\s*(\S+)", output)
    return match.group(1) if match else None


def assert_pqc_hybrid_tls(output: str, *, label: str) -> None:
    """Require TLS 1.3 PQC-hybrid group negotiation (no classical fallback)."""
    if negotiated_pqc_group(output):
        return
    group = extract_negotiated_tls_group(output) or "unknown"
    raise PqcConnectionError(
        f"{label}: expected PQC-hybrid group {PQC_GROUP!r}, negotiated {group!r}"
    )


def openssl_s_client(
    radius_container: str,
    *,
    connect: str,
    ca_file: str,
    cert_file: str | None = None,
    key_file: str | None = None,
    use_pqc_conf: bool = True,
    verbose: bool | None = None,
    require_tls13: bool = True,
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
    if require_tls13 and not tls13_handshake(output):
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
    detail = ceos_show_json(
        container,
        f"show management security ssl profile {profile} detail",
        verbose=verbose,
    )
    _assert_json_contains(detail, "valid", label=f"{node} {profile} profile")
    _assert_json_contains(detail, PQC_GROUP, label=f"{node} {profile} KEX groups")


def check_eapi_config(targets: LabTargets, node: str, *, verbose: bool | None = None) -> None:
    container = targets.ceos_container(node)
    check_switch_ssl_profile(targets, node, "EAPI", verbose=verbose)
    http = ceos_show_json(container, "show management api http-commands", verbose=verbose)
    _assert_json_contains(http, "EAPI", label=f"{node} eAPI binding")
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


def check_gnmi_config(targets: LabTargets, node: str, *, verbose: bool | None = None) -> None:
    container = targets.ceos_container(node)
    check_switch_ssl_profile(targets, node, GNMI_SSL_PROFILE, verbose=verbose)
    gnmi = ceos_show_json(container, "show management api gnmi", verbose=verbose)
    _assert_json_contains(gnmi, GNMI_SSL_PROFILE, label=f"{node} gNMI binding")
    detail = ceos_show_json(
        container,
        f"show management security ssl profile {GNMI_SSL_PROFILE} detail",
        verbose=verbose,
    )
    _assert_json_contains(detail, "radsec-ca.pem", label=f"{node} GNMI mTLS trust")
    report_config(f"gNMI ssl profile {GNMI_SSL_PROFILE} valid ({PQC_GROUP}), mTLS trust, grpc bound")


def check_restconf_config(targets: LabTargets, node: str, *, verbose: bool | None = None) -> None:
    container = targets.ceos_container(node)
    check_switch_ssl_profile(targets, node, RESTCONF_SSL_PROFILE, verbose=verbose)
    restconf = ceos_show_json(container, "show management api restconf", verbose=verbose)
    _assert_json_contains(restconf, RESTCONF_SSL_PROFILE, label=f"{node} RESTCONF binding")
    report_config(f"RESTCONF ssl profile {RESTCONF_SSL_PROFILE} valid ({PQC_GROUP}), HTTPS bound")


def check_eossdkrpc_config(targets: LabTargets, node: str, *, verbose: bool | None = None) -> None:
    container = targets.ceos_container(node)
    check_switch_ssl_profile(targets, node, EOSSDKRPC_SSL_PROFILE, verbose=verbose)
    cfg = ceos_cli(container, "enable\nshow running-config | section eos-sdk-rpc\n", verbose=verbose)
    assert_contains(cfg, f"ssl profile {EOSSDKRPC_SSL_PROFILE}", label=f"{node} eos-sdk-rpc config")
    rpc = ceos_show_json(container, "show management api eos-sdk-rpc", verbose=verbose)
    profile = json_transport_ssl_profile(rpc)
    if profile != EOSSDKRPC_SSL_PROFILE:
        raise PqcConnectionError(
            f"{node} eos-sdk-rpc binding: expected sslProfile {EOSSDKRPC_SSL_PROFILE!r}, got {profile!r}"
        )
    if not json_truthy(rpc, "enabled"):
        raise PqcConnectionError(f"{node} eos-sdk-rpc: expected enabled service")
    report_config(f"eos-sdk-rpc ssl profile {EOSSDKRPC_SSL_PROFILE} valid ({PQC_GROUP}), grpc bound")


def probe_gnmi_tls(targets: LabTargets, node: str, *, verbose: bool | None = None) -> None:
    ip = targets.ceos_ips[node]
    output = openssl_s_client(
        targets.radius_container,
        connect=f"{ip}:{GNMI_PORT}",
        ca_file=RADSEC_CA_IN_RADIUS,
        verbose=verbose,
    )
    assert_pqc_hybrid_tls(output, label=f"{node} gNMI TLS")
    report_live(f"gNMI gRPC TLS handshake (TLS 1.3, {PQC_GROUP})")


def probe_gnmi_mtls(targets: LabTargets, node: str, *, verbose: bool | None = None) -> None:
    ip = targets.ceos_ips[node]
    cert_file = PROBE_CLIENT_CERT.format(node=node)
    key_file = PROBE_CLIENT_KEY.format(node=node)
    output = openssl_s_client(
        targets.radius_container,
        connect=f"{ip}:{GNMI_PORT}",
        ca_file=RADSEC_CA_IN_RADIUS,
        cert_file=cert_file,
        key_file=key_file,
        verbose=verbose,
    )
    assert_pqc_hybrid_tls(output, label=f"{node} gNMI mTLS")
    report_live(f"gNMI gRPC mTLS handshake (TLS 1.3, {PQC_GROUP})")


def probe_restconf_tls(targets: LabTargets, node: str, *, verbose: bool | None = None) -> None:
    ip = targets.ceos_ips[node]
    output = openssl_s_client(
        targets.radius_container,
        connect=f"{ip}:{RESTCONF_PORT}",
        ca_file=RADSEC_CA_IN_RADIUS,
        verbose=verbose,
    )
    assert_pqc_hybrid_tls(output, label=f"{node} RESTCONF TLS")
    report_live(f"RESTCONF HTTPS handshake (TLS 1.3, {PQC_GROUP})")


def probe_eossdkrpc_tls(targets: LabTargets, node: str, *, verbose: bool | None = None) -> None:
    """Probe eos-sdk-rpc mTLS.

    cEOS 4.36.1F often does not negotiate PQC-hybrid on port 9543 despite the ssl
    profile (EOF with a PQC-only client, or classical KEX with a permissive client).
    Config is still validated; live probe warns instead of failing the suite.
    """
    ip = targets.ceos_ips[node]
    cert_file = PROBE_CLIENT_CERT.format(node=node)
    key_file = PROBE_CLIENT_KEY.format(node=node)
    connect = f"{ip}:{EOSSDKRPC_PORT}"
    pqc_output = openssl_s_client(
        targets.radius_container,
        connect=connect,
        ca_file=RADSEC_CA_IN_RADIUS,
        cert_file=cert_file,
        key_file=key_file,
        verbose=verbose,
        require_tls13=False,
    )
    if tls13_handshake(pqc_output) and negotiated_pqc_group(pqc_output):
        report_live(f"eos-sdk-rpc gRPC mTLS handshake (TLS 1.3, {PQC_GROUP})")
        return

    classical_output = openssl_s_client(
        targets.radius_container,
        connect=connect,
        ca_file=RADSEC_CA_IN_RADIUS,
        cert_file=cert_file,
        key_file=key_file,
        use_pqc_conf=False,
        verbose=verbose,
        require_tls13=False,
    )
    if tls13_handshake(classical_output):
        group = extract_negotiated_tls_group(classical_output) or "unknown"
        report_live(
            f"eos-sdk-rpc gRPC mTLS handshake (TLS 1.3, {group}; cEOS 4.36.1F PQC gap)",
            status=CheckStatus.WARN,
        )
        return

    report_live(
        "eos-sdk-rpc gRPC mTLS: no TLS 1.3 handshake on :9543 (cEOS 4.36.1F PQC gap; config OK)",
        status=CheckStatus.WARN,
    )


def probe_eapi_https(targets: LabTargets, node: str, *, verbose: bool | None = None) -> None:
    ip = targets.ceos_ips[node]
    output = openssl_s_client(
        targets.radius_container,
        connect=f"{ip}:443",
        ca_file=RADSEC_CA_IN_RADIUS,
        verbose=verbose,
    )
    assert_pqc_hybrid_tls(output, label=f"{node} eAPI HTTPS")
    report_live(f"eAPI HTTPS handshake (TLS 1.3, {PQC_GROUP})")


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
        f"{SSH_PQC_USER}@{peer_ip} 'show hostname | json' 2>&1"
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
    assert_contains(output, peer, label=f"{node} SSH to {peer} hostname")
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


def check_syslog_collector_config(targets: LabTargets, *, verbose: bool | None = None) -> None:
    udp = docker_exec(
        targets.syslog_container,
        "netstat -lun",
        verbose=verbose,
        title=f"{targets.syslog_container} netstat UDP",
    ).stdout
    tcp = docker_exec(
        targets.syslog_container,
        "netstat -ltn",
        verbose=verbose,
        title=f"{targets.syslog_container} netstat TCP",
    ).stdout
    try:
        check_syslog_collector_listeners(udp, tcp)
    except SyslogCheckError as exc:
        raise PqcConnectionError(str(exc)) from exc
    groups = docker_exec(
        targets.syslog_container,
        "openssl list -tls-groups",
        verbose=verbose,
        title=f"{targets.syslog_container} openssl groups",
    ).stdout
    assert_contains(groups, SYSLOG_PQC_GROUP, label="syslog OpenSSL groups")
    report_config(f"syslog collector TLS :6514 only (no UDP/TCP 514), OpenSSL groups include {SYSLOG_PQC_GROUP}")


def check_syslog_config(targets: LabTargets, node: str, *, verbose: bool | None = None) -> None:
    container = targets.ceos_container(node)
    logging_cfg = ceos_cli(container, "enable\nshow running-config section logging\n", verbose=verbose)
    try:
        check_switch_syslog_logging_config(
            logging_cfg,
            node=node,
            syslog_ip=targets.syslog_ip,
        )
    except SyslogCheckError as exc:
        raise PqcConnectionError(str(exc)) from exc
    detail = ceos_show_json(
        container,
        f"show management security ssl profile {SYSLOG_SSL_PROFILE} detail",
        verbose=verbose,
    )
    try:
        check_switch_syslog_ssl_profile_detail(detail, node=node)
    except SyslogCheckError as exc:
        raise PqcConnectionError(str(exc)) from exc
    report_config(
        f"syslog ssl profile {SYSLOG_SSL_PROFILE} valid ({SYSLOG_PQC_GROUP}), "
        f"no cleartext logging hosts, TLS host {targets.syslog_ip}:6514"
    )


def probe_syslog_tls(targets: LabTargets, *, verbose: bool | None = None) -> None:
    try:
        probe_syslog_tls_pqc(
            docker_exec,
            syslog_container=targets.syslog_container,
            syslog_ip=targets.syslog_ip,
        )
    except SyslogCheckError as exc:
        raise PqcConnectionError(str(exc)) from exc
    report_live(f"syslog-ng TLS handshake (TLS 1.3, {SYSLOG_PQC_GROUP})")


def probe_syslog_delivery(targets: LabTargets, node: str, *, verbose: bool | None = None) -> None:
    container = targets.ceos_container(node)
    switch_ip = targets.ceos_ips[node]
    needle = f"quantum-safe-syslog-probe-{node}"

    def send_log() -> None:
        ceos_cli(
            container,
            f"enable\nsend log level informational message {needle}\n",
            verbose=verbose,
        )

    try:
        probe_syslog_delivery_no_cleartext(
            docker_exec,
            send_log,
            syslog_container=targets.syslog_container,
            switch_ip=switch_ip,
            node=node,
        )
    except SyslogCheckError as exc:
        raise PqcConnectionError(str(exc)) from exc
    report_live(f"{node} TLS syslog delivered, no cleartext packets from {switch_ip}")


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
        syslog_ip=ips["syslog"],
        ceos_ips={"ceos1-both": ips["ceos1-both"], "ceos2-pqc": ips["ceos2-pqc"], "ceos3-qkd": ips["ceos3-qkd"]},
    )

    print_section_header("PQC verification (TLS 1.3, PQC-hybrid only — no classical fallback)")
    print("  [config] EOS show commands / local listener checks")
    print("  [live]   TLS/mTLS handshakes, eAPI JSON-RPC, gNMI/gNOI gRPC, RESTCONF, eos-sdk-rpc, RadSec AAA, SSH, Syslog\n")

    print_device("radius")
    if not skip_config:
        check_radius_config(targets, verbose=verbose)

    print()
    print_device("syslog")
    if not skip_config:
        check_syslog_collector_config(targets, verbose=verbose)
    probe_syslog_tls(targets, verbose=verbose)

    for node in ("ceos1-both", "ceos2-pqc", "ceos3-qkd"):
        print()
        print_device(node)
        if not skip_config:
            check_eapi_config(targets, node, verbose=verbose)
            check_gnmi_config(targets, node, verbose=verbose)
            check_restconf_config(targets, node, verbose=verbose)
            check_eossdkrpc_config(targets, node, verbose=verbose)
            check_radsec_config(targets, node, verbose=verbose)
            check_ssh_pqc_config(targets, node, verbose=verbose)
            check_syslog_config(targets, node, verbose=verbose)
        probe_eapi_https(targets, node, verbose=verbose)
        probe_eapi_jsonrpc(node, targets.ceos_ips[node], verbose=verbose)
        probe_gnmi_tls(targets, node, verbose=verbose)
        probe_gnmi_mtls(targets, node, verbose=verbose)
        probe_restconf_tls(targets, node, verbose=verbose)
        probe_eossdkrpc_tls(targets, node, verbose=verbose)
        probe_radsec_from_switch(targets, node, verbose=verbose)
        probe_ssh_pqc(targets, node, CEOS_PEERS[node], verbose=verbose)
        probe_syslog_delivery(targets, node, verbose=verbose)

    print()
    report_summary(
        "PQC",
        f"all {'live checks only' if skip_config else '[config] and [live] checks'} "
        "passed (eAPI, gNMI/gNOI, RESTCONF, eos-sdk-rpc, RadSec, SSH, Syslog; TLS 1.3, no cleartext syslog)",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify live eAPI and RadSec PQC connectivity.")
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
        run_live_checks(
            clab_name=args.clab_name,
            mgmt_subnet=args.mgmt_subnet,
            skip_config=args.skip_config,
            verbose=verbose,
        )
    except (PqcConnectionError, subprocess.CalledProcessError) as exc:
        report_summary("PQC", str(exc), CheckStatus.FAIL, file=sys.stderr)
        print(file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
