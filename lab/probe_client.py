"""PQC probe client for live lab checks (test-runner, radius fallback, or host)."""

from __future__ import annotations

import os
import subprocess
from typing import Literal

from lab.topology_contract import (
    GNMI_GET_PATH,
    LAB_NAME,
    PROBE_CA_TEST_RUNNER,
    PROBE_CLIENT_CERT,
    PROBE_CLIENT_CERT_TEST_RUNNER,
    PROBE_CLIENT_KEY,
    PROBE_CLIENT_KEY_TEST_RUNNER,
    PROBE_SYSLOG_CA_TEST_RUNNER,
    SSH_PQC_KEX,
    TLS_PQC_GROUP,
    container_name,
    hostport,
)
from lab.verbose import echo_command, echo_result, verbose_enabled

DEFAULT_PROBE_NODE = "test-runner"
PROBE_RADIUS_NODE = "radius"
PROBE_HOST_MODE = "host"
OPENSSL_PQC_CNF = "/etc/probe/openssl-pqc.cnf"
RADIUS_OPENSSL_PQC_CNF = "/etc/raddb/openssl-pqc.cnf"
RADIUS_PROBE_CA = "/etc/raddb/certs/radsec/ca.pem"

ProbeClientMode = Literal["test-runner", "radius", "host"]


def probe_client_mode() -> ProbeClientMode:
    """Return the active probe client (PROBE_CLIENT env overrides default)."""
    raw = os.environ.get("PROBE_CLIENT", DEFAULT_PROBE_NODE).strip().lower()
    if raw in (DEFAULT_PROBE_NODE, "test_runner"):
        return DEFAULT_PROBE_NODE
    if raw == PROBE_RADIUS_NODE:
        return PROBE_RADIUS_NODE
    if raw == PROBE_HOST_MODE:
        return PROBE_HOST_MODE
    raise ValueError(
        f"unsupported PROBE_CLIENT={raw!r} "
        f"(expected {DEFAULT_PROBE_NODE!r}, {PROBE_RADIUS_NODE!r}, or {PROBE_HOST_MODE!r})"
    )


def probe_node_name(mode: ProbeClientMode | None = None) -> str:
    """Return the topology node name used for docker-exec probes."""
    resolved = mode or probe_client_mode()
    if resolved == PROBE_HOST_MODE:
        raise ValueError("host probe mode has no container node")
    if resolved == PROBE_RADIUS_NODE:
        return PROBE_RADIUS_NODE
    return DEFAULT_PROBE_NODE


def probe_container(*, clab_name: str = LAB_NAME, mode: ProbeClientMode | None = None) -> str:
    """Return the Docker container name for the active probe client."""
    return container_name(probe_node_name(mode), lab_name=clab_name)


def docker_exec_probe(
    command: str,
    *,
    clab_name: str = LAB_NAME,
    mode: ProbeClientMode | None = None,
    input_text: str = "",
    check: bool = True,
    verbose: bool | None = None,
    title: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a shell command inside the configured probe client container."""
    container = probe_container(clab_name=clab_name, mode=mode)
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
        raise subprocess.CalledProcessError(
            result.returncode,
            argv,
            output=result.stdout,
            stderr=detail,
        )
    return result


def probe_ca_path(mode: ProbeClientMode | None = None) -> str:
    """Return the CA bundle path for RadSec/eAPI/gNMI probes."""
    resolved = mode or probe_client_mode()
    if resolved == PROBE_RADIUS_NODE:
        return RADIUS_PROBE_CA
    return PROBE_CA_TEST_RUNNER


def probe_syslog_ca_path(mode: ProbeClientMode | None = None) -> str:
    """Return the CA bundle path for syslog collector TLS probes."""
    resolved = mode or probe_client_mode()
    if resolved == PROBE_RADIUS_NODE:
        return "/etc/raddb/certs/radsec/ca.pem"
    return PROBE_SYSLOG_CA_TEST_RUNNER


def probe_client_cert_path(node: str, mode: ProbeClientMode | None = None) -> str:
    """Return the mTLS client certificate path for the given switch node."""
    resolved = mode or probe_client_mode()
    if resolved == PROBE_RADIUS_NODE:
        return PROBE_CLIENT_CERT.format(node=node)
    return PROBE_CLIENT_CERT_TEST_RUNNER.format(node=node)


def probe_client_key_path(node: str, mode: ProbeClientMode | None = None) -> str:
    """Return the mTLS client key path for the given switch node."""
    resolved = mode or probe_client_mode()
    if resolved == PROBE_RADIUS_NODE:
        return PROBE_CLIENT_KEY.format(node=node)
    return PROBE_CLIENT_KEY_TEST_RUNNER.format(node=node)


def _openssl_env_prefix(mode: ProbeClientMode, *, use_pqc_conf: bool) -> str:
    if not use_pqc_conf:
        return ""
    if mode == PROBE_RADIUS_NODE:
        return f"OPENSSL_CONF={RADIUS_OPENSSL_PQC_CNF} "
    if mode == PROBE_HOST_MODE:
        return ""
    return f"OPENSSL_CONF={OPENSSL_PQC_CNF} "


def openssl_s_client_command(
    connect: str,
    *,
    ca_file: str | None = None,
    cert_file: str | None = None,
    key_file: str | None = None,
    groups: str | None = None,
    servername: str | None = None,
    use_pqc_conf: bool = True,
    mode: ProbeClientMode | None = None,
) -> str:
    """Return a shell command for an OpenSSL s_client TLS 1.3 probe."""
    resolved = mode or probe_client_mode()
    env_prefix = _openssl_env_prefix(resolved, use_pqc_conf=use_pqc_conf)
    cert_args = ""
    if cert_file and key_file:
        cert_args = f"-cert {cert_file} -key {key_file} "
    ca_arg = f"-CAfile {ca_file} " if ca_file else ""
    groups_arg = f"-groups {groups} " if groups else ""
    sni_arg = f"-servername {servername} " if servername else ""
    return (
        f"{env_prefix}openssl s_client -connect {connect} -tls1_3 "
        f"{ca_arg}{cert_args}{groups_arg}{sni_arg}-brief </dev/null 2>&1"
    )


def run_openssl_s_client(
    *,
    connect: str,
    ca_file: str | None = None,
    cert_file: str | None = None,
    key_file: str | None = None,
    groups: str | None = None,
    servername: str | None = None,
    use_pqc_conf: bool = True,
    clab_name: str = LAB_NAME,
    verbose: bool | None = None,
    mode: ProbeClientMode | None = None,
    title: str | None = None,
) -> str:
    """Execute OpenSSL s_client and return combined stdout/stderr."""
    resolved = mode or probe_client_mode()
    command = openssl_s_client_command(
        connect,
        ca_file=ca_file,
        cert_file=cert_file,
        key_file=key_file,
        groups=groups,
        servername=servername,
        use_pqc_conf=use_pqc_conf,
        mode=resolved,
    )
    show = verbose_enabled(verbose)

    if resolved == PROBE_HOST_MODE:
        argv = ["sh", "-c", command]
        if show:
            echo_command(title or f"openssl s_client {connect} (host)", argv)
        result = subprocess.run(argv, capture_output=True, text=True, check=False)
        if show:
            echo_result(result)
    else:
        result = docker_exec_probe(
            command,
            clab_name=clab_name,
            mode=resolved,
            check=False,
            verbose=verbose,
            title=title or f"openssl s_client {connect} ({probe_node_name(resolved)})",
        )
    return result.stdout + result.stderr


def _curl_openssl_env(mode: ProbeClientMode) -> str:
    return _openssl_env_prefix(mode, use_pqc_conf=True)


def curl_eapi_command(
    url: str,
    payload: str,
    *,
    user: str = "admin:",
    mode: ProbeClientMode | None = None,
) -> str:
    """Return a shell command for eAPI command-api over TLS 1.3."""
    resolved = mode or probe_client_mode()
    env_prefix = _curl_openssl_env(resolved)
    return (
        f"{env_prefix}curl -sk --tlsv1.3 --tls-max 1.3 "
        f"-u {user!s} {url!r} "
        f"-H 'Content-Type: application/json' "
        f"-d {payload!r}"
    )


def curl_eapi_argv(
    url: str,
    payload: str,
    *,
    user: str = "admin:",
) -> list[str]:
    """Build host-side curl argv for eAPI command-api (PROBE_CLIENT=host)."""
    return [
        "curl",
        "-sk",
        "--tlsv1.3",
        "--tls-max",
        "1.3",
        "-u",
        user,
        url,
        "-H",
        "Content-Type: application/json",
        "-d",
        payload,
    ]


def run_curl_eapi(
    *,
    node: str,
    switch_ip: str,
    payload: str,
    clab_name: str = LAB_NAME,
    port: int = 443,
    user: str = "admin:",
    verbose: bool | None = None,
    mode: ProbeClientMode | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute eAPI command-api against a switch mgmt address."""
    resolved = mode or probe_client_mode()
    url = f"https://{hostport(switch_ip, port)}/command-api"
    show = verbose_enabled(verbose)

    if resolved == PROBE_HOST_MODE:
        argv = curl_eapi_argv(url, payload, user=user)
        if show:
            echo_command(f"{node} eAPI command-api", argv)
        result = subprocess.run(argv, capture_output=True, text=True, check=False)
        if show:
            echo_result(result, format_json=True)
        return result

    command = curl_eapi_command(url, payload, user=user, mode=resolved)
    return docker_exec_probe(
        command,
        clab_name=clab_name,
        mode=resolved,
        verbose=verbose,
        title=f"{node} eAPI command-api ({probe_node_name(resolved)})",
    )


def gnmi_get_command(
    target: str,
    *,
    ca_file: str,
    cert_file: str,
    key_file: str,
    path: str = GNMI_GET_PATH,
) -> str:
    """Return a shell command for a gNMI GET over TLS 1.3 (PQC-safe client)."""
    return (
        f"gnmic -a {target!r} "
        f"--tls-ca {ca_file} "
        f"--tls-cert {cert_file} "
        f"--tls-key {key_file} "
        f"--tls-version 1.3 --tls-min-version 1.3 --tls-max-version 1.3 "
        f"get --path {path!r} --format json"
    )


def run_gnmi_get(
    *,
    node: str,
    switch_ip: str,
    port: int,
    clab_name: str = LAB_NAME,
    path: str = GNMI_GET_PATH,
    verbose: bool | None = None,
    mode: ProbeClientMode | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute a gNMI GET against a switch gRPC endpoint."""
    resolved = mode or probe_client_mode()
    if resolved == PROBE_HOST_MODE:
        raise ValueError("gNMI GET probe requires test-runner or radius container (gnmic not on host)")
    target = hostport(switch_ip, port)
    command = gnmi_get_command(
        target,
        ca_file=probe_ca_path(resolved),
        cert_file=probe_client_cert_path(node, resolved),
        key_file=probe_client_key_path(node, resolved),
        path=path,
    )
    return docker_exec_probe(
        command,
        clab_name=clab_name,
        mode=resolved,
        check=False,
        verbose=verbose,
        title=f"{node} gNMI GET {path} ({probe_node_name(resolved)}, TLS 1.3, {TLS_PQC_GROUP})",
    )


def ssh_pqc_command(
    mgmt_ip: str,
    *,
    user: str = "admin",
    remote_command: str = "show hostname | json",
    kex: str = SSH_PQC_KEX,
) -> str:
    """Return a shell command for an SSH PQC-hybrid probe."""
    return (
        f"ssh -vvv "
        f"-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
        f"-o PubkeyAuthentication=no -o PreferredAuthentications=keyboard-interactive "
        f"-o KexAlgorithms={kex} "
        f"{user}@{mgmt_ip} {remote_command!r} 2>&1"
    )


def ssh_pqc_argv(
    mgmt_ip: str,
    *,
    user: str = "admin",
    remote_command: str = "show hostname | json",
    kex: str = SSH_PQC_KEX,
) -> list[str]:
    """Build host-side ssh argv for a PQC probe (PROBE_CLIENT=host)."""
    return [
        "ssh",
        "-vvv",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "PubkeyAuthentication=no",
        "-o",
        "PreferredAuthentications=keyboard-interactive",
        "-o",
        f"KexAlgorithms={kex}",
        f"{user}@{mgmt_ip}",
        remote_command,
    ]


def ssh_probe_mode(mode: ProbeClientMode | None = None) -> ProbeClientMode:
    """Return the probe client used for SSH (test-runner unless host override)."""
    resolved = mode or probe_client_mode()
    if resolved == PROBE_HOST_MODE:
        return PROBE_HOST_MODE
    return DEFAULT_PROBE_NODE


def live_check_prefix(mode: ProbeClientMode | None = None) -> str:
    """Return the [live / …] prefix for checks executed from the probe client."""
    resolved = mode or probe_client_mode()
    if resolved == PROBE_HOST_MODE:
        label = PROBE_HOST_MODE
    else:
        label = probe_node_name(resolved)
    return f"[live / {label}]  "


def run_ssh_pqc_probe(
    *,
    node: str,
    switch_ip: str,
    clab_name: str = LAB_NAME,
    user: str = "admin",
    remote_command: str = "show hostname | json",
    verbose: bool | None = None,
    mode: ProbeClientMode | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute an SSH PQC-hybrid probe against a switch mgmt address."""
    resolved = ssh_probe_mode(mode)
    show = verbose_enabled(verbose)

    if resolved == PROBE_HOST_MODE:
        argv = ssh_pqc_argv(switch_ip, user=user, remote_command=remote_command)
        if show:
            echo_command(f"{node} SSH PQC (host)", argv)
        result = subprocess.run(argv, capture_output=True, text=True, check=False)
        if show:
            echo_result(result)
        return result

    command = ssh_pqc_command(switch_ip, user=user, remote_command=remote_command)
    return docker_exec_probe(
        command,
        clab_name=clab_name,
        mode=resolved,
        verbose=verbose,
        title=f"{node} SSH PQC ({probe_node_name(resolved)}, {switch_ip})",
    )
