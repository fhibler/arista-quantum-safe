"""Live lab checks for TLS 1.3 and PQC-hybrid connectivity (eAPI + gNMI + RadSec + SSH)."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
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
    capture_eos_syslog_tls_key_share_group,
    check_switch_syslog_logging_config,
    check_switch_syslog_ssl_profile_detail,
    check_syslog_collector_listeners,
    is_pqc_hybrid_key_share_group,
    probe_syslog_delivery_no_cleartext,
    probe_syslog_tls_pqc,
    tls_key_share_group_name,
    wait_for_syslog_healthy,
)
from lab.topology_contract import (
    EOSSDKRPC_SSL_PROFILE,
    EOSSDKRPC_PORT,
    GNMI_PORT,
    GNMI_SSL_PROFILE,
    IP_FAMILIES,
    IP_FAMILY_IPV4,
    IP_FAMILY_IPV6,
    LAB_NAME,
    RADSEC_PORT,
    RESTCONF_PORT,
    RESTCONF_SSL_PROFILE,
    SYSLOG_PORT,
    SYSLOG_SSL_PROFILE,
    TLS_PQC_GROUP,
    container_name,
    family_label,
    hostport,
    mgmt_ips_for_subnet,
    mgmt_ipv6_ips_for_subnet,
)
from lab.probe_client import (
    ProbeClientMode,
    live_check_prefix,
    probe_ca_path,
    probe_client_cert_path,
    probe_client_key_path,
    run_curl_eapi,
    run_gnmi_get,
    run_openssl_s_client,
    run_ssh_pqc_probe,
    ssh_probe_mode,
)
from lab.report import (
    CheckStatus,
    print_check_group,
    print_device,
    print_section_header,
    report_check,
    report_ok,
    report_skip,
    report_summary,
    report_warn,
)
from lab.verbose import echo_command, echo_result, verbose_enabled

SSH_PQC_KEX = "mlkem768x25519-sha256"
SSH_PQC_USER = "admin"
CEOS_NODES = ("ceos1-both", "ceos2-pqc", "ceos3-qkd")
EOSSDKRPC_CLASSICAL_PROBE_GROUP = "secp256r1"
PQC_GROUP = TLS_PQC_GROUP
RADSEC_AAA_SUCCESS_MARKER = "successfully authenticated"
RADSEC_AAA_POLL_INTERVAL_SEC = 2
RADSEC_AAA_POLL_ATTEMPTS = 15


@dataclass(frozen=True)
class LabTargets:
    clab_name: str
    mgmt_ips: dict[str, str]
    mgmt_ips6: dict[str, str]
    ceos_ips: dict[str, str]
    ceos_ips6: dict[str, str]

    @property
    def radius_ip(self) -> str:
        return self.mgmt_ips6["radius"]

    @property
    def syslog_ips(self) -> tuple[str, str]:
        return self.mgmt_ips["syslog"], self.mgmt_ips6["syslog"]

    def service_ip(self, service: str, family: str = IP_FAMILY_IPV4) -> str:
        if family == IP_FAMILY_IPV4:
            return self.mgmt_ips[service]
        return self.mgmt_ips6[service]

    def ceos_mgmt_ip(self, node: str, family: str = IP_FAMILY_IPV4) -> str:
        if family == IP_FAMILY_IPV4:
            return self.ceos_ips[node]
        return self.ceos_ips6[node]

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


def report_live(
    detail: str,
    *,
    status: CheckStatus = CheckStatus.OK,
    probe_client: bool = False,
    probe_mode: ProbeClientMode | None = None,
) -> None:
    """Report a live connectivity check (handshake, API call, AAA test)."""
    prefix = live_check_prefix(probe_mode) if probe_client else "[live]  "
    if status is CheckStatus.WARN:
        report_warn(prefix, detail)
    elif status is CheckStatus.FAIL:
        report_check(prefix, detail, CheckStatus.FAIL)
    elif status is CheckStatus.SKIP:
        report_skip(prefix, detail)
    else:
        report_ok(prefix, detail)


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
    if match:
        group = match.group(1)
        if group not in ("<NULL>", "(NONE)"):
            return group
    if "Peer Temp Key: ECDH, prime256v1" in output:
        return "secp256r1"
    if re.search(r"Peer Temp Key: ECDH, X25519\b", output):
        return "x25519"
    return None


def assert_pqc_hybrid_tls(output: str, *, label: str) -> None:
    """Require TLS 1.3 PQC-hybrid group negotiation (no classical fallback)."""
    if not tls13_handshake(output):
        raise PqcConnectionError(f"{label}: TLS 1.3 handshake failed:\n{output[-800:]}")
    if negotiated_pqc_group(output):
        return
    group = extract_negotiated_tls_group(output) or "unknown"
    raise PqcConnectionError(
        f"{label}: expected PQC-hybrid group {PQC_GROUP!r}, negotiated {group!r}"
    )


def probe_gnmi_tls(
    targets: LabTargets,
    node: str,
    *,
    family: str = IP_FAMILY_IPV4,
    verbose: bool | None = None,
) -> None:
    ip = targets.ceos_mgmt_ip(node, family)
    output = run_openssl_s_client(
        connect=hostport(ip, GNMI_PORT),
        ca_file=probe_ca_path(),
        clab_name=targets.clab_name,
        verbose=verbose,
    )
    assert_pqc_hybrid_tls(output, label=f"{node} gNMI TLS")
    report_live(f"gNMI gRPC TLS handshake ({family_label(family)}, TLS 1.3, {PQC_GROUP})", probe_client=True)


def probe_gnmi_mtls(
    targets: LabTargets,
    node: str,
    *,
    family: str = IP_FAMILY_IPV4,
    verbose: bool | None = None,
) -> None:
    ip = targets.ceos_mgmt_ip(node, family)
    output = run_openssl_s_client(
        connect=hostport(ip, GNMI_PORT),
        ca_file=probe_ca_path(),
        cert_file=probe_client_cert_path(node),
        key_file=probe_client_key_path(node),
        clab_name=targets.clab_name,
        verbose=verbose,
    )
    assert_pqc_hybrid_tls(output, label=f"{node} gNMI mTLS")
    report_live(f"gNMI gRPC mTLS handshake ({family_label(family)}, TLS 1.3, {PQC_GROUP})", probe_client=True)


def probe_gnmi_get(
    targets: LabTargets,
    node: str,
    *,
    family: str = IP_FAMILY_IPV4,
    verbose: bool | None = None,
) -> None:
    """gNMI GET over mTLS (TLS 1.3 only; PQC-hybrid required by server profile)."""
    ip = targets.ceos_mgmt_ip(node, family)
    result = run_gnmi_get(
        node=node,
        switch_ip=ip,
        port=GNMI_PORT,
        clab_name=targets.clab_name,
        verbose=verbose,
    )
    body = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        detail = body or f"gnmic exit {result.returncode}"
        raise PqcConnectionError(f"{node} gNMI GET: {detail[-500:]}")
    if node not in body:
        raise PqcConnectionError(f"{node} gNMI GET: expected hostname {node!r} in response: {body[:200]}")
    report_live(
        f"gNMI gRPC GET hostname ({family_label(family)}, TLS 1.3, {PQC_GROUP})",
        probe_client=True,
    )


def probe_restconf_tls(
    targets: LabTargets,
    node: str,
    *,
    family: str = IP_FAMILY_IPV4,
    verbose: bool | None = None,
) -> None:
    ip = targets.ceos_mgmt_ip(node, family)
    output = run_openssl_s_client(
        connect=hostport(ip, RESTCONF_PORT),
        ca_file=probe_ca_path(),
        clab_name=targets.clab_name,
        verbose=verbose,
    )
    assert_pqc_hybrid_tls(output, label=f"{node} RESTCONF TLS")
    report_live(f"RESTCONF HTTPS handshake ({family_label(family)}, TLS 1.3, {PQC_GROUP})", probe_client=True)


def probe_eossdkrpc_tls(
    targets: LabTargets,
    node: str,
    *,
    family: str = IP_FAMILY_IPV4,
    verbose: bool | None = None,
) -> None:
    """Probe eos-sdk-rpc mTLS.

    EOS often does not negotiate PQC-hybrid on port 9543 despite the ssl
    profile. Probes PQC-only first; on failure, falls back to explicit ``secp256r1``
    (the classical group that completes TLS 1.3 in this lab).
    Config is still validated; live probe warns instead of failing the suite.
    IPv6 live probes are skipped: ``local interface Management0`` binds the primary
    IPv4 address only (unlike ``vrf MGMT`` gNMI on :6030).
    """
    if family == IP_FAMILY_IPV6:
        report_live(
            f"eos-sdk-rpc gRPC mTLS handshake ({family_label(family)}), skipped — "
            f"local interface Management0 binds IPv4 only",
            status=CheckStatus.SKIP,
            probe_client=True,
        )
        return

    ip = targets.ceos_mgmt_ip(node, family)
    cert_file = probe_client_cert_path(node)
    key_file = probe_client_key_path(node)
    connect = hostport(ip, EOSSDKRPC_PORT)
    common = dict(
        connect=connect,
        ca_file=probe_ca_path(),
        cert_file=cert_file,
        key_file=key_file,
        clab_name=targets.clab_name,
        verbose=verbose,
    )

    pqc_output = run_openssl_s_client(**common)
    if tls13_handshake(pqc_output) and negotiated_pqc_group(pqc_output):
        report_live(
            f"eos-sdk-rpc gRPC mTLS handshake ({family_label(family)}, TLS 1.3, {PQC_GROUP})",
            probe_client=True,
        )
        return

    secp256r1_output = run_openssl_s_client(
        **common,
        use_pqc_conf=False,
        groups=EOSSDKRPC_CLASSICAL_PROBE_GROUP,
    )
    if tls13_handshake(secp256r1_output):
        group = extract_negotiated_tls_group(secp256r1_output) or EOSSDKRPC_CLASSICAL_PROBE_GROUP
        report_live(
            f"eos-sdk-rpc gRPC mTLS handshake ({family_label(family)}), "
            f"not PQC-safe, TLS 1.3 compliant — negotiated {group} "
            f"(explicit client group {EOSSDKRPC_CLASSICAL_PROBE_GROUP})",
            status=CheckStatus.WARN,
            probe_client=True,
        )
        return

    report_live(
        f"eos-sdk-rpc gRPC mTLS ({family_label(family)}), not PQC-safe — "
        f"no TLS 1.3 handshake on :9543",
        status=CheckStatus.WARN,
        probe_client=True,
    )


def probe_eapi_https(
    targets: LabTargets,
    node: str,
    *,
    family: str = IP_FAMILY_IPV4,
    verbose: bool | None = None,
) -> None:
    ip = targets.ceos_mgmt_ip(node, family)
    output = run_openssl_s_client(
        connect=hostport(ip, 443),
        ca_file=probe_ca_path(),
        clab_name=targets.clab_name,
        verbose=verbose,
    )
    assert_pqc_hybrid_tls(output, label=f"{node} eAPI HTTPS")
    report_live(f"eAPI HTTPS handshake ({family_label(family)}, TLS 1.3, {PQC_GROUP})", probe_client=True)


def probe_eapi(
    node: str,
    switch_ip: str,
    *,
    family: str = IP_FAMILY_IPV4,
    verbose: bool | None = None,
    clab_name: str = LAB_NAME,
) -> None:
    payload = (
        '{"jsonrpc":"2.0","method":"runCmds",'
        '"params":{"version":1,"cmds":["show version"],"format":"json"},"id":1}'
    )
    result = run_curl_eapi(
        node=node,
        switch_ip=switch_ip,
        payload=payload,
        clab_name=clab_name,
        verbose=verbose,
    )
    body = result.stdout.strip()
    if result.returncode != 0 or not body:
        detail = result.stderr.strip() or body or f"curl exit {result.returncode}"
        raise PqcConnectionError(f"{node} eAPI command-api: {detail}")
    if "modelName" not in body and "version" not in body.lower():
        raise PqcConnectionError(f"{node} eAPI command-api: unexpected response: {body[:200]}")
    report_live(f"eAPI command-api runCmds ({family_label(family)})", probe_client=True)


# Backward-compatible alias.
probe_eapi_jsonrpc = probe_eapi


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


def probe_radsec_collector_tls(
    targets: LabTargets,
    node: str,
    *,
    family: str = IP_FAMILY_IPV4,
    verbose: bool | None = None,
) -> None:
    """RadSec collector TLS handshake from probe client with switch client cert."""
    radius_ip = targets.service_ip("radius", family)
    output = run_openssl_s_client(
        connect=hostport(radius_ip, RADSEC_PORT),
        ca_file=probe_ca_path(),
        cert_file=probe_client_cert_path(node),
        key_file=probe_client_key_path(node),
        clab_name=targets.clab_name,
        verbose=verbose,
    )
    assert_pqc_hybrid_tls(output, label=f"{node} RadSec collector TLS")
    report_live(f"RadSec collector TLS handshake ({family_label(family)}, TLS 1.3, {PQC_GROUP})", probe_client=True)


def negotiated_ssh_pqc_kex(output: str) -> bool:
    return f"kex: algorithm: {SSH_PQC_KEX}" in output


def probe_ssh_pqc(
    targets: LabTargets,
    node: str,
    *,
    family: str = IP_FAMILY_IPV4,
    verbose: bool | None = None,
) -> None:
    """SSH from the probe client (test-runner by default) to switch mgmt over VRF MGMT."""
    mgmt_ip = targets.ceos_mgmt_ip(node, family)
    result = run_ssh_pqc_probe(
        node=node,
        switch_ip=mgmt_ip,
        clab_name=targets.clab_name,
        user=SSH_PQC_USER,
        verbose=verbose,
    )
    output = result.stdout + result.stderr
    if result.returncode != 0:
        detail = output.strip() or f"exit {result.returncode}"
        raise PqcConnectionError(f"{node} SSH ({mgmt_ip}): {detail[-500:]}")
    if not negotiated_ssh_pqc_kex(output):
        raise PqcConnectionError(
            f"{node} SSH ({mgmt_ip}): expected kex {SSH_PQC_KEX!r} in handshake output"
        )
    assert_contains(output, node, label=f"{node} SSH hostname")
    report_live(
        f"SSH ({family_label(family)}, {SSH_PQC_KEX})",
        probe_client=True,
        probe_mode=ssh_probe_mode(),
    )


def radsec_aaa_test_commands(radius_addr: str) -> str:
    return (
        "enable\n"
        f"test aaa group RADIUS server {radius_addr} tls port {RADSEC_PORT} vrf MGMT\n"
    )


def radsec_aaa_test_succeeded(output: str) -> bool:
    return RADSEC_AAA_SUCCESS_MARKER in output


def probe_radsec_from_switch(
    targets: LabTargets,
    node: str,
    *,
    family: str = IP_FAMILY_IPV4,
    verbose: bool | None = None,
) -> None:
    """Run ``test aaa`` from a switch, retrying transient RadSec/TLS failures."""
    container = targets.ceos_container(node)
    radius_addr = targets.service_ip("radius", family)
    commands = radsec_aaa_test_commands(radius_addr)
    label = f"{node} RadSec AAA test ({family_label(family)})"
    last_output = ""
    for attempt in range(RADSEC_AAA_POLL_ATTEMPTS):
        if attempt:
            time.sleep(RADSEC_AAA_POLL_INTERVAL_SEC)
        last_output = ceos_cli(container, commands, verbose=verbose)
        if radsec_aaa_test_succeeded(last_output):
            report_live(f"RadSec AAA via test aaa ({family_label(family)}) → radius:{RADSEC_PORT}")
            return
    assert_contains(last_output, RADSEC_AAA_SUCCESS_MARKER, label=label)


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
            syslog_ips=targets.syslog_ips,
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
    syslog_ipv4, syslog_ipv6 = targets.syslog_ips
    report_config(
        f"syslog ssl profile {SYSLOG_SSL_PROFILE} valid ({SYSLOG_PQC_GROUP}), "
        f"no cleartext logging hosts, TLS hosts {syslog_ipv4}:6514, {syslog_ipv6}:6514"
    )


def probe_syslog_tls(
    targets: LabTargets,
    *,
    family: str = IP_FAMILY_IPV4,
    verbose: bool | None = None,
) -> None:
    syslog_ip = targets.service_ip("syslog", family)
    try:
        probe_syslog_tls_pqc(
            syslog_ip=syslog_ip,
            clab_name=targets.clab_name,
            syslog_container=targets.syslog_container,
            verbose=verbose,
        )
    except SyslogCheckError as exc:
        raise PqcConnectionError(str(exc)) from exc
    report_live(
        f"syslog-ng collector TLS handshake ({family_label(family)}, TLS 1.3, {SYSLOG_PQC_GROUP})",
        probe_client=True,
    )


def probe_syslog_delivery(
    targets: LabTargets,
    node: str,
    *,
    family: str = IP_FAMILY_IPV4,
    verbose: bool | None = None,
) -> None:
    container = targets.ceos_container(node)
    switch_ip = targets.ceos_mgmt_ip(node, family)
    syslog_ipv4, syslog_ipv6 = targets.syslog_ips
    syslog_ip = syslog_ipv4 if family == IP_FAMILY_IPV4 else syslog_ipv6
    needle = f"quantum-safe-syslog-probe-{node}-{family}"

    def send_log() -> None:
        ceos_cli(
            container,
            f"enable\nsend log level informational message {needle}\n",
            verbose=verbose,
        )

    def bounce_logging_hosts() -> None:
        """Drop and restore all remote syslog TLS sessions (dual-stack)."""
        remove_lines = "".join(
            f"no logging vrf MGMT host {ip} {SYSLOG_PORT} "
            f"protocol tls ssl-profile {SYSLOG_SSL_PROFILE}\n"
            for ip in (syslog_ipv4, syslog_ipv6)
        )
        add_lines = "".join(
            f"logging vrf MGMT host {ip} {SYSLOG_PORT} "
            f"protocol tls ssl-profile {SYSLOG_SSL_PROFILE}\n"
            for ip in (syslog_ipv4, syslog_ipv6)
        )
        ceos_cli(
            container,
            f"enable\nconfigure\n{remove_lines}end\n",
            verbose=verbose,
        )
        time.sleep(3)
        ceos_cli(
            container,
            f"enable\nconfigure\n{add_lines}end\n",
            verbose=verbose,
        )

    try:
        probe_syslog_delivery_no_cleartext(
            docker_exec,
            send_log,
            syslog_container=targets.syslog_container,
            switch_ip=switch_ip,
            node=node,
            needle=needle,
            marker_id=f"{node}-{family}",
        )
    except SyslogCheckError as exc:
        raise PqcConnectionError(str(exc)) from exc

    negotiated_group: int | None = None
    for attempt in range(2):
        negotiated_group = capture_eos_syslog_tls_key_share_group(
            switch_ip=switch_ip,
            bounce_logging=bounce_logging_hosts,
            syslog_container=targets.syslog_container,
            settle_sec=4.0 + attempt * 2,
            verbose=verbose,
        )
        if negotiated_group is not None:
            break
        time.sleep(1)
    if negotiated_group is not None and is_pqc_hybrid_key_share_group(negotiated_group):
        report_live(
            f"{node} TLS syslog delivered ({family_label(family)}), "
            f"wire KEX {tls_key_share_group_name(negotiated_group)}"
        )
        return

    if negotiated_group is not None:
        group_name = tls_key_share_group_name(negotiated_group)
        report_live(
            f"{node} TLS syslog delivered ({family_label(family)}), "
            f"not PQC-safe, TLS 1.3 compliant — wire KEX {group_name}",
            status=CheckStatus.WARN,
        )
        return

    report_live(
        f"{node} TLS syslog delivered ({family_label(family)}), "
        f"not PQC-safe, TLS 1.3 compliant — wire KEX not verified",
        status=CheckStatus.WARN,
    )


def run_live_checks(
    *,
    clab_name: str,
    mgmt_subnet: str,
    skip_config: bool = False,
    verbose: bool | None = None,
) -> None:
    show = verbose_enabled(verbose)
    ips = mgmt_ips_for_subnet(mgmt_subnet)
    ips6 = mgmt_ipv6_ips_for_subnet()
    targets = LabTargets(
        clab_name=clab_name,
        mgmt_ips=ips,
        mgmt_ips6=ips6,
        ceos_ips={"ceos1-both": ips["ceos1-both"], "ceos2-pqc": ips["ceos2-pqc"], "ceos3-qkd": ips["ceos3-qkd"]},
        ceos_ips6={"ceos1-both": ips6["ceos1-both"], "ceos2-pqc": ips6["ceos2-pqc"], "ceos3-qkd": ips6["ceos3-qkd"]},
    )

    print_section_header("PQC verification (TLS 1.3, PQC-hybrid only — no classical fallback)")
    print("  [config] EOS show commands / local listener checks")
    print("  [live]   EOS-side checks (RadSec AAA, syslog delivery, wire KEX when capture available)")
    print("  [live / test-runner]  TLS/mTLS handshakes, eAPI, gNMI GET, RESTCONF, eos-sdk-rpc, RadSec collector, SSH, syslog collector")
    print("  grouped by check type; IPv4 and IPv6 under each\n")

    print_device("radius")
    if not skip_config:
        check_radius_config(targets, verbose=verbose)

    print()
    print_device("syslog")
    if not skip_config:
        check_syslog_collector_config(targets, verbose=verbose)
    wait_for_syslog_healthy(targets.syslog_container)
    print_check_group("Collector TLS")
    for family in IP_FAMILIES:
        probe_syslog_tls(targets, family=family, verbose=verbose)

    for node in CEOS_NODES:
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

        print_check_group("eAPI")
        for family in IP_FAMILIES:
            probe_eapi_https(targets, node, family=family, verbose=verbose)
            probe_eapi(
                node,
                targets.ceos_mgmt_ip(node, family),
                family=family,
                verbose=verbose,
                clab_name=targets.clab_name,
            )

        print_check_group("gNMI")
        for family in IP_FAMILIES:
            probe_gnmi_tls(targets, node, family=family, verbose=verbose)
            probe_gnmi_mtls(targets, node, family=family, verbose=verbose)
            probe_gnmi_get(targets, node, family=family, verbose=verbose)

        print_check_group("RESTCONF")
        for family in IP_FAMILIES:
            probe_restconf_tls(targets, node, family=family, verbose=verbose)

        print_check_group("eos-sdk-rpc")
        for family in IP_FAMILIES:
            probe_eossdkrpc_tls(targets, node, family=family, verbose=verbose)

        print_check_group("SSH")
        for family in IP_FAMILIES:
            probe_ssh_pqc(targets, node, family=family, verbose=verbose)

        print_check_group("Syslog")
        for family in IP_FAMILIES:
            probe_syslog_delivery(targets, node, family=family, verbose=verbose)

        print_check_group("RadSec")
        for family in IP_FAMILIES:
            probe_radsec_collector_tls(targets, node, family=family, verbose=verbose)
            probe_radsec_from_switch(targets, node, family=family, verbose=verbose)

    print()
    report_summary(
        "PQC",
        f"all {'live checks only' if skip_config else '[config] and [live] checks'} "
        "passed (eAPI, gNMI/gNOI, RESTCONF, eos-sdk-rpc, RadSec, SSH, Syslog; "
        "WARN on syslog/eos-sdk-rpc not PQC-safe (TLS 1.3 compliant where verified)",
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
