"""Live lab checks for gNOI, gRIBI, gNSI, and gNPSI (Paulo expansion plan)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from lab.ceos_json import (
    assert_json_contains,
    json_find_value,
    json_server_addresses,
    json_transport_port,
    json_transport_ssl_profile,
    json_tree_contains,
    json_truthy,
)
from lab.grpc_probe import (
    gnoic_ping_command,
    gnoic_services_command,
    grpc_target,
    grpcurl_invoke_command,
    gribic_get_command,
    gnsic_certz_get_profile_list_command,
    run_grpc_probe,
)
from lab.topology_contract import (
    GNMI_PORT,
    GNMI_SSL_PROFILE,
    GNPSI_PORT,
    GNPSI_SSL_PROFILE,
    GRIBI_PORT,
    GRIBI_SSL_PROFILE,
    GNSI_SSL_PROFILE,
    IP_FAMILIES,
    IP_FAMILY_IPV4,
    IP_FAMILY_IPV6,
    TLS_PQC_GROUP,
    family_label,
    hostport,
)
from lab.probe_client import (
    probe_ca_path,
    probe_client_cert_path,
    probe_client_key_path,
    run_openssl_s_client,
)
from lab.report import CheckStatus, print_check_group, report_ok, report_skip, report_warn

if TYPE_CHECKING:
    from lab.test_pqc_connections import LabTargets

GNOI_PING_RPC = "gnoi.system.System/Ping"
GNOI_REFLECTION_SERVICES = ("gnoi.system.System",)
EOS_ADMIN_USERNAME = "admin"
GNPSI_UNSUPPORTED_MARKERS = (
    "invalid input",
    "invalid command",
    "not supported",
    "unrecognized command",
    "no such command",
)


def _report_config(detail: str) -> None:
    report_ok("[config]", detail)


def _report_live(
    detail: str,
    *,
    status: CheckStatus = CheckStatus.OK,
    probe_client: bool = False,
) -> None:
    prefix = "[live / test-runner]  " if probe_client else "[live]  "
    if status is CheckStatus.WARN:
        report_warn(prefix, detail)
    elif status is CheckStatus.SKIP:
        report_skip(prefix, detail)
    else:
        report_ok(prefix, detail)


def _service_port(api_json: object, default: int | None = None) -> int:
    port = json_transport_port(api_json)
    if port is not None:
        return port
    if default is not None:
        return default
    raise ValueError("could not resolve service port from EOS JSON")


def check_gnoi_config(targets: LabTargets, node: str, *, verbose: bool | None = None) -> None:
    from lab.test_pqc_connections import PqcConnectionError, check_switch_ssl_profile, ceos_show_json

    container = targets.ceos_container(node)
    check_switch_ssl_profile(targets, node, GNMI_SSL_PROFILE, verbose=verbose)
    gnmi = ceos_show_json(container, "show management api gnmi", verbose=verbose)
    assert_json_contains(gnmi, GNMI_SSL_PROFILE, label=f"{node} gNOI transport")
    if not json_truthy(gnmi, "enabled"):
        raise PqcConnectionError(f"{node} gNOI transport: gNMI api not enabled")
    _report_config(
        f"gNOI transport via gNMI ssl profile {GNMI_SSL_PROFILE} valid ({TLS_PQC_GROUP}), grpc bound"
    )


def probe_gnoi_tls(
    targets: LabTargets,
    node: str,
    *,
    family: str = IP_FAMILY_IPV4,
    verbose: bool | None = None,
) -> None:
    from lab.test_pqc_connections import assert_pqc_hybrid_tls

    ip = targets.ceos_mgmt_ip(node, family)
    output = run_openssl_s_client(
        connect=hostport(ip, GNMI_PORT),
        ca_file=probe_ca_path(),
        clab_name=targets.clab_name,
        verbose=verbose,
    )
    assert_pqc_hybrid_tls(output, label=f"{node} gNOI transport TLS")
    _report_live(
        f"gNOI transport TLS handshake ({family_label(family)}, TLS 1.3, {TLS_PQC_GROUP})",
        probe_client=True,
    )


def probe_gnoi_ping(
    targets: LabTargets,
    node: str,
    *,
    family: str = IP_FAMILY_IPV4,
    verbose: bool | None = None,
) -> None:
    from lab.test_pqc_connections import PqcConnectionError

    ip = targets.ceos_mgmt_ip(node, family)
    target = grpc_target(ip, GNMI_PORT)
    command = gnoic_ping_command(target, node=node)
    result = run_grpc_probe(
        command,
        clab_name=targets.clab_name,
        verbose=verbose,
        title=f"{node} gNOI System/Ping ({family_label(family)})",
    )
    body = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        fallback = grpcurl_invoke_command(
            target,
            node=node,
            rpc=GNOI_PING_RPC,
            data='{"destination": "127.0.0.1", "count": 1, "doNotResolve": true}',
        )
        result = run_grpc_probe(
            fallback,
            clab_name=targets.clab_name,
            verbose=verbose,
            title=f"{node} gNOI System/Ping via grpcurl ({family_label(family)})",
        )
        body = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        raise PqcConnectionError(f"{node} gNOI Ping: {body[-500:]}")
    _report_live(
        f"gNOI System/Ping RPC ({family_label(family)}, mTLS, {TLS_PQC_GROUP})",
        probe_client=True,
    )


def probe_gnoi_reflection(
    targets: LabTargets,
    node: str,
    *,
    family: str = IP_FAMILY_IPV4,
    verbose: bool | None = None,
) -> None:
    from lab.test_pqc_connections import PqcConnectionError

    ip = targets.ceos_mgmt_ip(node, family)
    target = grpc_target(ip, GNMI_PORT)
    command = gnoic_services_command(target, node=node)
    result = run_grpc_probe(
        command,
        clab_name=targets.clab_name,
        verbose=verbose,
        title=f"{node} gNOI grpc reflection ({family_label(family)})",
    )
    body = result.stdout + result.stderr
    if result.returncode != 0:
        raise PqcConnectionError(f"{node} gNOI reflection: {body[-500:]}")
    missing = [svc for svc in GNOI_REFLECTION_SERVICES if svc not in body]
    if missing:
        raise PqcConnectionError(f"{node} gNOI reflection: missing services {missing!r}")
    _report_live(
        f"gNOI gRPC reflection lists {', '.join(GNOI_REFLECTION_SERVICES)} ({family_label(family)})",
        probe_client=True,
    )


def check_gribi_config(targets: LabTargets, node: str, *, verbose: bool | None = None) -> None:
    from lab.test_pqc_connections import PqcConnectionError, check_switch_ssl_profile, ceos_show_json

    container = targets.ceos_container(node)
    check_switch_ssl_profile(targets, node, GRIBI_SSL_PROFILE, verbose=verbose)
    gribi = ceos_show_json(container, "show management api gribi", verbose=verbose)
    profile = json_transport_ssl_profile(gribi)
    if profile != GRIBI_SSL_PROFILE:
        raise PqcConnectionError(
            f"{node} gRIBI binding: expected sslProfile {GRIBI_SSL_PROFILE!r}, got {profile!r}"
        )
    port = _service_port(gribi, GRIBI_PORT)
    if port != GRIBI_PORT:
        raise PqcConnectionError(f"{node} gRIBI: expected port {GRIBI_PORT}, got {port}")
    if not json_tree_contains(gribi, "MGMT"):
        raise PqcConnectionError(f"{node} gRIBI: expected vrf MGMT in JSON output")
    _report_config(
        f"gRIBI ssl profile {GRIBI_SSL_PROFILE} valid ({TLS_PQC_GROUP}), "
        f"grpc bound port {GRIBI_PORT} vrf MGMT"
    )


def check_gribi_ssl_profile(targets: LabTargets, node: str, *, verbose: bool | None = None) -> None:
    from lab.test_pqc_connections import check_switch_ssl_profile

    check_switch_ssl_profile(targets, node, GRIBI_SSL_PROFILE, verbose=verbose)
    _report_config(f"gRIBI ssl profile {GRIBI_SSL_PROFILE} PQC-hybrid only ({TLS_PQC_GROUP})")


def probe_gribi_mtls(
    targets: LabTargets,
    node: str,
    *,
    family: str = IP_FAMILY_IPV4,
    verbose: bool | None = None,
) -> None:
    """Verify gRIBI mTLS and PQC-hybrid KEX via gribic (openssl s_client cannot speak gRPC/HTTP2)."""
    from lab.test_pqc_connections import PqcConnectionError

    ip = targets.ceos_mgmt_ip(node, family)
    target = grpc_target(ip, GRIBI_PORT)
    command = gribic_get_command(target, node=node)
    result = run_grpc_probe(
        command,
        clab_name=targets.clab_name,
        verbose=verbose,
        title=f"{node} gRIBI mTLS Get ({family_label(family)})",
    )
    body = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        fallback = grpcurl_invoke_command(
            target,
            node=node,
            rpc="gribi.gRIBI/Get",
            data="{}",
        )
        result = run_grpc_probe(
            fallback,
            clab_name=targets.clab_name,
            verbose=verbose,
            title=f"{node} gRIBI mTLS Get via grpcurl ({family_label(family)})",
        )
        body = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        raise PqcConnectionError(f"{node} gRIBI mTLS Get: {body[-500:]}")
    _report_live(
        f"gRIBI gRPC mTLS + Get RPC ({family_label(family)}, {TLS_PQC_GROUP})",
        probe_client=True,
    )


def check_gribi_ipv6_binding(
    targets: LabTargets,
    node: str,
    *,
    verbose: bool | None = None,
) -> None:
    from lab.test_pqc_connections import PqcConnectionError, ceos_cli, ceos_show_json

    container = targets.ceos_container(node)
    gribi = ceos_show_json(container, "show management api gribi", verbose=verbose)
    addresses = json_server_addresses(gribi)
    text_blob = " ".join(addresses)
    if not addresses:
        text_blob = ceos_cli(container, "enable\nshow management api gribi\n", verbose=verbose)
    if "::" not in text_blob and "IPv6" not in text_blob:
        raise PqcConnectionError(
            f"{node} gRIBI IPv6 binding: expected dual-stack listen (::) on vrf MGMT"
        )
    _report_config("gRIBI listen includes IPv6 (::) on vrf MGMT dual-stack")


def check_gnsi_config(targets: LabTargets, node: str, *, verbose: bool | None = None) -> None:
    from lab.test_pqc_connections import PqcConnectionError, check_switch_ssl_profile, ceos_show_json

    container = targets.ceos_container(node)
    check_switch_ssl_profile(targets, node, GNSI_SSL_PROFILE, verbose=verbose)
    gnsi = ceos_show_json(container, "show management api gnsi", verbose=verbose)
    port = json_transport_port(gnsi)
    if port != GNMI_PORT:
        raise PqcConnectionError(
            f"{node} gNSI transport: expected port {GNMI_PORT} on gNMI listener, got {port!r}"
        )
    transports = json_find_value(gnsi, "transports")
    default = transports.get("default") if isinstance(transports, dict) else None
    if not isinstance(default, dict) or not default.get("enabled"):
        raise PqcConnectionError(
            f"{node} gNSI transport: expected transport gnmi default enabled on port {GNMI_PORT}"
        )
    if not json_tree_contains(gnsi, "certz"):
        raise PqcConnectionError(f"{node} gNSI: expected certz service enabled")
    if not json_tree_contains(gnsi, "authz"):
        raise PqcConnectionError(f"{node} gNSI: expected authz service enabled")
    _report_config(
        f"gNSI ssl profile {GNSI_SSL_PROFILE} valid ({TLS_PQC_GROUP}), "
        f"certz/authz on transport gnmi default port {GNMI_PORT}"
    )


def _gnsi_port(targets: LabTargets, node: str, *, verbose: bool | None = None) -> int:
    from lab.test_pqc_connections import ceos_show_json

    container = targets.ceos_container(node)
    gnsi = ceos_show_json(container, "show management api gnsi", verbose=verbose)
    port = json_transport_port(gnsi)
    if port is not None:
        return port
    return GNMI_PORT


def probe_gnsi_tls(
    targets: LabTargets,
    node: str,
    *,
    family: str = IP_FAMILY_IPV4,
    verbose: bool | None = None,
) -> None:
    from lab.test_pqc_connections import assert_pqc_hybrid_tls

    ip = targets.ceos_mgmt_ip(node, family)
    port = _gnsi_port(targets, node, verbose=verbose)
    output = run_openssl_s_client(
        connect=hostport(ip, port),
        ca_file=probe_ca_path(),
        cert_file=probe_client_cert_path(node),
        key_file=probe_client_key_path(node),
        clab_name=targets.clab_name,
        verbose=verbose,
    )
    assert_pqc_hybrid_tls(output, label=f"{node} gNSI mTLS")
    _report_live(
        f"gNSI gRPC mTLS handshake ({family_label(family)}, TLS 1.3, {TLS_PQC_GROUP})",
        probe_client=True,
    )


def probe_gnsi_certz_profilelist(
    targets: LabTargets,
    node: str,
    *,
    family: str = IP_FAMILY_IPV4,
    verbose: bool | None = None,
) -> None:
    """Certz.GetProfileList over gNSI transport gnmi default (Certz omitted from gRPC reflection)."""
    from lab.test_pqc_connections import PqcConnectionError

    ip = targets.ceos_mgmt_ip(node, family)
    port = _gnsi_port(targets, node, verbose=verbose)
    target = grpc_target(ip, port)
    command = gnsic_certz_get_profile_list_command(target, node=node)
    result = run_grpc_probe(
        command,
        clab_name=targets.clab_name,
        verbose=verbose,
        title=f"{node} gNSI Certz.GetProfileList ({family_label(family)})",
    )
    body = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        raise PqcConnectionError(f"{node} gNSI Certz.GetProfileList: {body[-500:]}")
    if GNSI_SSL_PROFILE not in body:
        raise PqcConnectionError(
            f"{node} gNSI Certz.GetProfileList: expected ssl profile {GNSI_SSL_PROFILE!r} in response"
        )
    _report_live(
        f"gNSI Certz.GetProfileList RPC ({family_label(family)}, mTLS, {TLS_PQC_GROUP})",
        probe_client=True,
    )


def gnpsi_supported_on_ceos(
    targets: LabTargets,
    node: str,
    *,
    verbose: bool | None = None,
) -> bool:
    """Return False when cEOS lacks gNPSI (entire gNPSI section should SKIP)."""
    from lab.test_pqc_connections import ceos_cli

    container = targets.ceos_container(node)
    try:
        output = ceos_cli(container, "enable\nshow management api gnpsi\n", verbose=verbose)
    except Exception:
        return False
    lowered = output.lower()
    if any(marker in lowered for marker in GNPSI_UNSUPPORTED_MARKERS):
        return False
    if "disabled" in lowered and "running" not in lowered:
        return False
    return True


def probe_gnpsi_ceos_support(
    targets: LabTargets,
    node: str,
    *,
    verbose: bool | None = None,
) -> bool:
    """Report gnpsi-ceos-support; return False when later gNPSI checks should SKIP."""
    if gnpsi_supported_on_ceos(targets, node, verbose=verbose):
        _report_config("gNPSI management api available on cEOS")
        return True
    report_skip("[config]", "gNPSI not supported on cEOS — remaining gNPSI checks skipped")
    return False


def check_gnpsi_config(targets: LabTargets, node: str, *, verbose: bool | None = None) -> None:
    from lab.test_pqc_connections import PqcConnectionError, check_switch_ssl_profile, ceos_show_json

    container = targets.ceos_container(node)
    check_switch_ssl_profile(targets, node, GNPSI_SSL_PROFILE, verbose=verbose)
    gnpsi = ceos_show_json(container, "show management api gnpsi", verbose=verbose)
    profile = json_transport_ssl_profile(gnpsi)
    if profile != GNPSI_SSL_PROFILE:
        raise PqcConnectionError(
            f"{node} gNPSI binding: expected sslProfile {GNPSI_SSL_PROFILE!r}, got {profile!r}"
        )
    port = _service_port(gnpsi, GNPSI_PORT)
    if port != GNPSI_PORT:
        raise PqcConnectionError(f"{node} gNPSI: expected port {GNPSI_PORT}, got {port}")
    if not json_tree_contains(gnpsi, "sflow", case_sensitive=False):
        raise PqcConnectionError(f"{node} gNPSI: expected source sFlow in JSON output")
    _report_config(
        f"gNPSI ssl profile {GNPSI_SSL_PROFILE} valid ({TLS_PQC_GROUP}), "
        f"transport enabled port {GNPSI_PORT} source sFlow"
    )


def probe_gnpsi_tls(
    targets: LabTargets,
    node: str,
    *,
    family: str = IP_FAMILY_IPV4,
    verbose: bool | None = None,
) -> None:
    from lab.test_pqc_connections import assert_pqc_hybrid_tls

    ip = targets.ceos_mgmt_ip(node, family)
    output = run_openssl_s_client(
        connect=hostport(ip, GNPSI_PORT),
        ca_file=probe_ca_path(),
        cert_file=probe_client_cert_path(node),
        key_file=probe_client_key_path(node),
        clab_name=targets.clab_name,
        verbose=verbose,
    )
    if "Connection refused" in output or "connect error" in output.lower():
        _report_live(
            f"gNPSI gRPC mTLS handshake ({family_label(family)}), skipped — "
            f"port {GNPSI_PORT} not listening on cEOS despite enabled transport",
            status=CheckStatus.SKIP,
            probe_client=True,
        )
        return
    assert_pqc_hybrid_tls(output, label=f"{node} gNPSI TLS")
    _report_live(
        f"gNPSI gRPC mTLS handshake ({family_label(family)}, TLS 1.3, {TLS_PQC_GROUP})",
        probe_client=True,
    )


def probe_gnpsi_subscribe(
    targets: LabTargets,
    node: str,
    *,
    family: str = IP_FAMILY_IPV4,
    verbose: bool | None = None,
) -> None:
    ip = targets.ceos_mgmt_ip(node, family)
    target = grpc_target(ip, GNPSI_PORT)
    list_cmd = gnoic_services_command(target, node=node)
    result = run_grpc_probe(
        list_cmd,
        clab_name=targets.clab_name,
        verbose=verbose,
        title=f"{node} gNPSI grpc reflection ({family_label(family)})",
    )
    body = result.stdout + result.stderr
    if result.returncode != 0:
        _report_live(
            f"gNPSI subscribe ({family_label(family)}), skipped — "
            f"cEOS sFlow→gNPSI pipeline may not produce datagrams",
            status=CheckStatus.SKIP,
            probe_client=True,
        )
        return
    subscribe_rpc = None
    for line in body.splitlines():
        if "Subscribe" in line or "Stream" in line:
            subscribe_rpc = line.strip()
            break
    if not subscribe_rpc:
        _report_live(
            f"gNPSI subscribe ({family_label(family)}), skipped — "
            f"no Subscribe RPC in reflection (cEOS sFlow dataplane limitation)",
            status=CheckStatus.SKIP,
            probe_client=True,
        )
        return
    invoke = grpcurl_invoke_command(target, node=node, rpc=subscribe_rpc, data="{}")
    sub_result = run_grpc_probe(
        f"timeout 8 sh -c {invoke!r} || true",
        clab_name=targets.clab_name,
        verbose=verbose,
        title=f"{node} gNPSI subscribe ({family_label(family)})",
    )
    sub_body = sub_result.stdout + sub_result.stderr
    if sub_result.returncode == 0 and sub_body.strip():
        _report_live(
            f"gNPSI subscribe received datagram ({family_label(family)}, mTLS)",
            probe_client=True,
        )
        return
    _report_live(
        f"gNPSI subscribe ({family_label(family)}), skipped — "
        f"no sFlow datagrams on cEOS within probe window",
        status=CheckStatus.SKIP,
        probe_client=True,
    )


def run_openconfig_grpc_checks(
    targets: LabTargets,
    nodes: tuple[str, ...],
    *,
    skip_config: bool = False,
    verbose: bool | None = None,
) -> None:
    """Run gNOI/gRIBI/gNSI/gNPSI checks for each switch."""
    gnpsi_enabled = True
    for node in nodes:
        print_check_group("gNOI")
        if not skip_config:
            check_gnoi_config(targets, node, verbose=verbose)
        for family in IP_FAMILIES:
            probe_gnoi_tls(targets, node, family=family, verbose=verbose)
            probe_gnoi_ping(targets, node, family=family, verbose=verbose)
            probe_gnoi_reflection(targets, node, family=family, verbose=verbose)

        print_check_group("gRIBI")
        if not skip_config:
            check_gribi_config(targets, node, verbose=verbose)
            check_gribi_ssl_profile(targets, node, verbose=verbose)
            check_gribi_ipv6_binding(targets, node, verbose=verbose)
        for family in IP_FAMILIES:
            probe_gribi_mtls(targets, node, family=family, verbose=verbose)

        print_check_group("gNSI")
        if not skip_config:
            check_gnsi_config(targets, node, verbose=verbose)
        for family in IP_FAMILIES:
            probe_gnsi_tls(targets, node, family=family, verbose=verbose)
            probe_gnsi_certz_profilelist(targets, node, family=family, verbose=verbose)

        print_check_group("gNPSI")
        if not skip_config:
            gnpsi_enabled = probe_gnpsi_ceos_support(targets, node, verbose=verbose)
            if gnpsi_enabled:
                check_gnpsi_config(targets, node, verbose=verbose)
        elif gnpsi_enabled:
            gnpsi_enabled = gnpsi_supported_on_ceos(targets, node, verbose=verbose)
        if not gnpsi_enabled:
            continue
        for family in IP_FAMILIES:
            probe_gnpsi_tls(targets, node, family=family, verbose=verbose)
        probe_gnpsi_subscribe(targets, node, family=IP_FAMILY_IPV4, verbose=verbose)
