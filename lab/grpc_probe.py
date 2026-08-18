"""gRPC probe helpers (grpcurl, gnoic, gribic, gnsic) for OpenConfig live checks."""

from __future__ import annotations

import subprocess

from lab.probe_client import (
    docker_exec_probe,
    probe_ca_path,
    probe_client_cert_path,
    probe_client_key_path,
)
from lab.topology_contract import EOS_ADMIN_USERNAME, LAB_NAME, hostport

GNOIC_TLS_ARGS = "--tls-version 1.3 --tls-min-version 1.3 --tls-max-version 1.3 "


def gnoic_mtls_args(node: str) -> str:
    """Return gnoic mTLS flags for a switch node."""
    return (
        f"--tls-ca {probe_ca_path()} "
        f"--tls-cert {probe_client_cert_path(node)} "
        f"--tls-key {probe_client_key_path(node)} "
        f"{GNOIC_TLS_ARGS}"
    )


def grpc_mtls_args(node: str) -> str:
    """Return grpcurl mTLS flags for a switch node.

    grpcurl uses Go crypto/tls (not OpenSSL). The test-runner image builds
    grpcurl with Go 1.24+ so X25519MLKEM768 is offered by default; see
    docs/misc/toolchain.md.
    """
    return (
        f"-cacert {probe_ca_path()} "
        f"-cert {probe_client_cert_path(node)} "
        f"-key {probe_client_key_path(node)} "
    )


def grpcurl_list_command(target: str, *, node: str) -> str:
    return f"grpcurl {grpc_mtls_args(node)} {target!r} list"


def grpcurl_invoke_command(
    target: str,
    *,
    node: str,
    rpc: str,
    data: str,
) -> str:
    return (
        f"grpcurl {grpc_mtls_args(node)} "
        f"-d {data!r} {target!r} {rpc}"
    )


def gnoic_services_command(target: str, *, node: str) -> str:
    """List gRPC services via server reflection."""
    return f"gnoic -a {target!r} {gnoic_mtls_args(node)}services"


def gnoic_ping_command(
    target: str,
    *,
    node: str,
    destination: str = "127.0.0.1",
    count: int = 1,
) -> str:
    return (
        f"gnoic -a {target!r} "
        f"{gnoic_mtls_args(node)}"
        f"system ping --destination {destination!r} --count {count} "
        f"--do-not-resolve"
    )


def gribic_get_command(target: str, *, node: str) -> str:
    return (
        f"gribic -a {target!r} "
        f"--tls-ca {probe_ca_path()} "
        f"--tls-cert {probe_client_cert_path(node)} "
        f"--tls-key {probe_client_key_path(node)} "
        f"get --aft IPv4"
    )


def gnsic_mtls_args(node: str) -> str:
    """Return gnsic mTLS flags for a switch node."""
    return (
        f"--tls-ca {probe_ca_path()} "
        f"--tls-cert {probe_client_cert_path(node)} "
        f"--tls-key {probe_client_key_path(node)} "
    )


def gnsic_certz_get_profile_list_command(target: str, *, node: str) -> str:
    """Invoke Certz.GetProfileList on the gNSI/gNMI shared listener (:6030).

    Certz requires gRPC metadata username auth on EOS even when mTLS is configured.
    """
    return (
        f"gnsic -u {EOS_ADMIN_USERNAME!r} -a {target!r} "
        f"{gnsic_mtls_args(node)}certz get-profile-list"
    )


def run_grpc_probe(
    command: str,
    *,
    clab_name: str = LAB_NAME,
    verbose: bool | None = None,
    title: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute a grpcurl/gnoic/gribic/gnsic command inside the test-runner container."""
    return docker_exec_probe(
        command,
        clab_name=clab_name,
        check=False,
        verbose=verbose,
        title=title,
    )


def grpc_target(switch_ip: str, port: int) -> str:
    return hostport(switch_ip, port)
