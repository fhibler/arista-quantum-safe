"""Live lab checks for dynamic MACsec (802.1X EAP-TLS + MKA) on the inter-switch link."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time

from lab.ceos_json import (
    CeosJsonError,
    assert_json_contains,
    extract_ckn_from_json,
    json_tree_contains,
    json_truthy,
    macsec_has_active_key,
    macsec_traffic_protected,
    mka_has_live_peers,
    parse_eos_json,
    ping_text_success,
)
from lab.report import CheckStatus, print_device, print_section_header, report_ok, report_summary
from lab.topology_contract import (
    CEOS_DATA_PLANE,
    DOT1X_EAP_IDENTITY,
    DOT1X_EAP_SSL_PROFILE,
    DOT1X_REAUTH_PERIOD_SEC,
    DOT1X_SUPPLICANT_PROFILE,
    LAB_NAME,
    MACSEC_PROFILE,
    QUADRA_MACSEC_INTF,
    QUADRA_MACSEC_PROFILE_MASTER,
    QUADRA_MACSEC_PROFILE_SLAVE,
    QUADRA_PEER_IP,
)
from lab.test_pqc_connections import LabTargets, ceos_cli, ceos_show_json, docker_exec

MACSEC_INTERFACE = "Ethernet1"
AUTHENTICATOR = "ceos1-both"
SUPPLICANT = "ceos2-pqc"
PQC_EAP_GROUP = "X25519MLKEM768"
INTER_SWITCH_PEER = {
    AUTHENTICATOR: CEOS_DATA_PLANE[SUPPLICANT]["eth1"].split("/")[0],
    SUPPLICANT: CEOS_DATA_PLANE[AUTHENTICATOR]["eth1"].split("/")[0],
}
QUADRA_MASTER = AUTHENTICATOR
QUADRA_SLAVE = "ceos3-qkd"
QUADRA_INTER_SWITCH_PEER = QUADRA_PEER_IP
REAUTH_WAIT_BUFFER_SEC = 15


class MacsecCheckError(RuntimeError):
    """Raised when a live MACsec/MKA check fails."""


def report_config(detail: str) -> None:
    report_ok("[config]", detail)


def report_live(detail: str) -> None:
    report_ok("[live]  ", detail)


def _assert_json_contains(obj, needle: str, *, label: str, case_sensitive: bool = True) -> None:
    try:
        assert_json_contains(obj, needle, label=label, case_sensitive=case_sensitive)
    except CeosJsonError as exc:
        raise MacsecCheckError(str(exc)) from exc


def extract_ckn(participants_output: str) -> str:
    """Extract CKN from text or JSON participant output (unit-test helper)."""
    if participants_output.lstrip().startswith("{"):
        try:
            return extract_ckn_from_json(parse_eos_json(participants_output))
        except CeosJsonError:
            pass
    match = re.search(r"CKN:\s+([0-9a-f]+)", participants_output, re.IGNORECASE)
    if not match:
        raise MacsecCheckError("expected CKN in mac security participants detail")
    return match.group(1)


def _assert_contains(text: str, needle: str, *, label: str) -> None:
    if needle not in text:
        raise MacsecCheckError(f"{label}: expected {needle!r} in output")


def _assert_contains_ci(text: str, needle: str, *, label: str) -> None:
    if needle.lower() not in text.lower():
        raise MacsecCheckError(f"{label}: expected {needle!r} in output")


def check_authenticator_config(container: str, *, verbose: bool | None = None) -> None:
    cfg = ceos_cli(container, "enable\nshow running-config | include dot1x\n", verbose=verbose)
    _assert_contains_ci(cfg, "aaa authentication dot1x default group RADIUS", label=f"{AUTHENTICATOR} dot1x aaa")
    _assert_contains(cfg, "dot1x system-auth-control", label=f"{AUTHENTICATOR} dot1x system-auth-control")
    intf = ceos_cli(
        container,
        f"enable\nshow running-config interface {MACSEC_INTERFACE}\n",
        verbose=verbose,
    )
    _assert_contains(intf, "dot1x pae authenticator", label=f"{AUTHENTICATOR} dot1x authenticator")
    _assert_contains(intf, "dot1x reauthentication", label=f"{AUTHENTICATOR} dot1x reauthentication")
    _assert_contains(
        intf,
        f"dot1x timeout reauth-period {DOT1X_REAUTH_PERIOD_SEC}",
        label=f"{AUTHENTICATOR} dot1x reauth period",
    )
    _assert_contains(
        intf,
        f"mac security profile {MACSEC_PROFILE}",
        label=f"{AUTHENTICATOR} macsec profile",
    )
    report_config(
        f"dot1x authenticator with reauth every {DOT1X_REAUTH_PERIOD_SEC}s, "
        f"mac security profile {MACSEC_PROFILE}, RadSec AAA group RADIUS"
    )


def check_supplicant_config(container: str, *, verbose: bool | None = None) -> None:
    cfg = ceos_cli(container, "enable\nshow running-config | section dot1x\n", verbose=verbose)
    _assert_contains(
        cfg,
        f"supplicant profile {DOT1X_SUPPLICANT_PROFILE}",
        label=f"{SUPPLICANT} supplicant profile",
    )
    _assert_contains(cfg, f"identity {DOT1X_EAP_IDENTITY}", label=f"{SUPPLICANT} EAP identity")
    _assert_contains(cfg, "eap-method tls", label=f"{SUPPLICANT} EAP-TLS")
    _assert_contains(cfg, f"ssl profile {DOT1X_EAP_SSL_PROFILE}", label=f"{SUPPLICANT} DOT1X ssl profile")
    intf = ceos_cli(
        container,
        f"enable\nshow running-config interface {MACSEC_INTERFACE}\n",
        verbose=verbose,
    )
    _assert_contains(
        intf,
        f"dot1x pae supplicant {DOT1X_SUPPLICANT_PROFILE}",
        label=f"{SUPPLICANT} dot1x supplicant",
    )
    report_config(
        f"dot1x supplicant {DOT1X_SUPPLICANT_PROFILE}, EAP-TLS + ssl profile {DOT1X_EAP_SSL_PROFILE}"
    )


def check_authenticator_dot1x(container: str, *, verbose: bool | None = None) -> None:
    hosts = ceos_show_json(container, "show dot1x hosts", verbose=verbose)
    _assert_json_contains(hosts, DOT1X_EAP_IDENTITY, label=f"{AUTHENTICATOR} dot1x host identity")
    _assert_json_contains(hosts, "SUCCESS", label=f"{AUTHENTICATOR} dot1x host state")
    detail = ceos_show_json(container, f"show dot1x interface {MACSEC_INTERFACE} detail", verbose=verbose)
    _assert_json_contains(
        detail,
        "authorized",
        label=f"{AUTHENTICATOR} dot1x port authorized",
        case_sensitive=False,
    )
    report_live(f"802.1X host {DOT1X_EAP_IDENTITY} SUCCESS, port Authorized")


def check_supplicant_dot1x(container: str, *, verbose: bool | None = None) -> None:
    output = ceos_show_json(container, "show dot1x supplicant", verbose=verbose)
    _assert_json_contains(output, DOT1X_EAP_IDENTITY, label=f"{SUPPLICANT} dot1x identity")
    _assert_json_contains(output, "success", label=f"{SUPPLICANT} dot1x status")
    _assert_json_contains(output, "tls", label=f"{SUPPLICANT} EAP method")
    _assert_json_contains(output, DOT1X_EAP_SSL_PROFILE, label=f"{SUPPLICANT} ssl profile")
    _assert_json_contains(output, PQC_EAP_GROUP, label=f"{SUPPLICANT} EAP-TLS PQC group")
    report_live(f"802.1X supplicant success (EAP-TLS, {PQC_EAP_GROUP})")


def check_macsec_interface(container: str, node: str, *, verbose: bool | None = None) -> None:
    output = ceos_show_json(
        container,
        f"show mac security interface {MACSEC_INTERFACE} detail",
        verbose=verbose,
    )
    _assert_json_contains(output, "True", label=f"{node} controlled port")
    if not macsec_traffic_protected(output):
        raise MacsecCheckError(f"{node}: expected protected MACsec traffic on {MACSEC_INTERFACE}")
    if not macsec_has_active_key(output):
        raise MacsecCheckError(f"{node}: expected active SAK (Key in use)")
    report_live(f"MACsec controlled port up, traffic encrypted on {MACSEC_INTERFACE}")


def check_mka_participants(container: str, node: str, *, verbose: bool | None = None) -> str:
    output = ceos_show_json(container, "show mac security participants detail", verbose=verbose)
    if not json_truthy(output, "success") and not json_tree_contains(output, "Success", case_sensitive=False):
        raise MacsecCheckError(f"{node}: expected successful MKA participant")
    if not mka_has_live_peers(output):
        raise MacsecCheckError(f"{node}: MKA live peer list is empty")
    try:
        ckn = extract_ckn_from_json(output)
    except CeosJsonError as exc:
        raise MacsecCheckError(str(exc)) from exc
    report_live(f"MKA participant CKN {ckn}, Success: True")
    return ckn


def count_radius_login_ok(radius_container: str, *, verbose: bool | None = None) -> int:
    result = docker_exec(
        radius_container,
        "grep -c 'Auth: Login OK' /var/log/radius/radius.log 2>/dev/null || true",
        check=False,
        verbose=verbose,
        title=f"{radius_container} Login OK count",
    )
    return int(result.stdout.strip() or 0)


def check_dot1x_reauth_cycle(
    targets: LabTargets,
    auth_container: str,
    supp_container: str,
    baseline_ckn: str,
    *,
    verbose: bool | None = None,
) -> None:
    wait_sec = DOT1X_REAUTH_PERIOD_SEC + REAUTH_WAIT_BUFFER_SEC
    baseline_ok = count_radius_login_ok(targets.radius_container, verbose=verbose)

    print()
    print_section_header(f"=== reauth (waiting {wait_sec}s for periodic 802.1X reauthentication) ===")
    time.sleep(wait_sec)

    check_authenticator_dot1x(auth_container, verbose=verbose)
    check_supplicant_dot1x(supp_container, verbose=verbose)

    auth_ckn = check_mka_participants(auth_container, AUTHENTICATOR, verbose=verbose)
    supp_ckn = check_mka_participants(supp_container, SUPPLICANT, verbose=verbose)
    if auth_ckn != baseline_ckn or supp_ckn != baseline_ckn:
        raise MacsecCheckError(
            f"CKN changed after reauth: baseline={baseline_ckn!r}, "
            f"{AUTHENTICATOR}={auth_ckn!r}, {SUPPLICANT}={supp_ckn!r}"
        )

    after_ok = count_radius_login_ok(targets.radius_container, verbose=verbose)
    if after_ok <= baseline_ok:
        raise MacsecCheckError(
            f"expected additional RADIUS Login OK after {wait_sec}s reauth wait "
            f"(baseline {baseline_ok}, after {after_ok})"
        )
    report_live(
        f"802.1X reauth cycle OK — port Authorized, CKN stable ({baseline_ckn}), "
        f"RADIUS Login OK count {baseline_ok} → {after_ok}"
    )


def probe_inter_switch_ping(
    container: str,
    node: str,
    peer_ip: str,
    *,
    interface: str = MACSEC_INTERFACE,
    verbose: bool | None = None,
) -> None:
    output = ceos_cli(container, f"enable\nping {peer_ip} repeat 3\n", verbose=verbose)
    if not ping_text_success(output):
        raise MacsecCheckError(f"{node} ping {peer_ip} over MACsec link: no successful replies")
    report_live(f"ping {peer_ip} over encrypted {interface} (0% loss)")


def check_static_macsec_config(
    container: str,
    node: str,
    *,
    profile: str,
    interface: str,
    verbose: bool | None = None,
) -> None:
    intf = ceos_cli(
        container,
        f"enable\nshow running-config interface {interface}\n",
        verbose=verbose,
    )
    _assert_contains(
        intf,
        f"mac security profile {profile}",
        label=f"{node} {interface} macsec profile",
    )
    macsec = ceos_cli(
        container,
        "enable\nshow running-config | section mac security\n",
        verbose=verbose,
    )
    _assert_contains(macsec, f"profile {profile}", label=f"{node} macsec profile {profile}")
    _assert_contains(macsec, "key source sak static", label=f"{node} static SAK profile")
    _assert_contains(macsec, "cipher aes256-gcm-xpn", label=f"{node} aes256-gcm-xpn cipher")
    report_config(f"static SAK profile {profile} on {interface}")


def check_static_macsec_interface(
    container: str,
    node: str,
    interface: str,
    *,
    verbose: bool | None = None,
) -> None:
    output = ceos_show_json(
        container,
        f"show mac security interface {interface} detail",
        verbose=verbose,
    )
    _assert_json_contains(output, "True", label=f"{node} controlled port")
    if not macsec_traffic_protected(output):
        raise MacsecCheckError(f"{node}: expected protected MACsec traffic on {interface}")
    if not macsec_has_active_key(output):
        raise MacsecCheckError(f"{node}: expected active SAK (Key in use) on {interface}")
    report_live(f"MACsec controlled port up, traffic encrypted on {interface}")


def run_quadra_macsec_checks(
    master_container: str,
    slave_container: str,
    *,
    skip_config: bool = False,
    verbose: bool | None = None,
) -> None:
    master_intf = QUADRA_MACSEC_INTF[QUADRA_MASTER]
    slave_intf = QUADRA_MACSEC_INTF[QUADRA_SLAVE]

    print_section_header("QuaDRA static MACsec (ceos1-both:eth3 ↔ ceos3-qkd:eth1)")

    print_device(QUADRA_MASTER)
    if not skip_config:
        check_static_macsec_config(
            master_container,
            QUADRA_MASTER,
            profile=QUADRA_MACSEC_PROFILE_MASTER,
            interface=master_intf,
            verbose=verbose,
        )
    check_static_macsec_interface(
        master_container,
        QUADRA_MASTER,
        master_intf,
        verbose=verbose,
    )

    print()
    print_device(QUADRA_SLAVE)
    if not skip_config:
        check_static_macsec_config(
            slave_container,
            QUADRA_SLAVE,
            profile=QUADRA_MACSEC_PROFILE_SLAVE,
            interface=slave_intf,
            verbose=verbose,
        )
    check_static_macsec_interface(
        slave_container,
        QUADRA_SLAVE,
        slave_intf,
        verbose=verbose,
    )

    print()
    print_device("QuaDRA link")
    probe_inter_switch_ping(
        master_container,
        QUADRA_MASTER,
        QUADRA_INTER_SWITCH_PEER[QUADRA_MASTER],
        interface=master_intf,
        verbose=verbose,
    )
    probe_inter_switch_ping(
        slave_container,
        QUADRA_SLAVE,
        QUADRA_INTER_SWITCH_PEER[QUADRA_SLAVE],
        interface=slave_intf,
        verbose=verbose,
    )


def run_macsec_checks(
    *,
    clab_name: str,
    mgmt_subnet: str,
    skip_config: bool = False,
    verify_reauth: bool = False,
    verbose: bool | None = None,
) -> None:
    from lab.topology_contract import mgmt_ips_for_subnet, mgmt_ipv6_ips_for_subnet

    ips = mgmt_ips_for_subnet(mgmt_subnet)
    ips6 = mgmt_ipv6_ips_for_subnet()
    targets = LabTargets(
        clab_name=clab_name,
        mgmt_ips=ips,
        mgmt_ips6=ips6,
        ceos_ips={AUTHENTICATOR: ips[AUTHENTICATOR], SUPPLICANT: ips[SUPPLICANT]},
        ceos_ips6={AUTHENTICATOR: ips6[AUTHENTICATOR], SUPPLICANT: ips6[SUPPLICANT]},
    )
    auth_container = targets.ceos_container(AUTHENTICATOR)
    supp_container = targets.ceos_container(SUPPLICANT)
    quadra_slave_container = targets.ceos_container(QUADRA_SLAVE)

    print_section_header("MACsec verification (802.1X EAP-TLS + MKA on inter-switch link)")
    print("  [config] EOS running-config stanzas")
    print("  [live]   dot1x state, MKA participants, encrypted traffic, inter-switch ping\n")

    print_device(AUTHENTICATOR)
    if not skip_config:
        check_authenticator_config(auth_container, verbose=verbose)
    check_authenticator_dot1x(auth_container, verbose=verbose)
    check_macsec_interface(auth_container, AUTHENTICATOR, verbose=verbose)
    auth_ckn = check_mka_participants(auth_container, AUTHENTICATOR, verbose=verbose)

    print()
    print_device(SUPPLICANT)
    if not skip_config:
        check_supplicant_config(supp_container, verbose=verbose)
    check_supplicant_dot1x(supp_container, verbose=verbose)
    check_macsec_interface(supp_container, SUPPLICANT, verbose=verbose)
    supp_ckn = check_mka_participants(supp_container, SUPPLICANT, verbose=verbose)

    if auth_ckn != supp_ckn:
        raise MacsecCheckError(
            f"CKN mismatch: {AUTHENTICATOR}={auth_ckn!r} vs {SUPPLICANT}={supp_ckn!r}"
        )
    report_live(f"matching CKN on both peers ({auth_ckn})")

    print()
    print_device("inter-switch")
    probe_inter_switch_ping(
        auth_container,
        AUTHENTICATOR,
        INTER_SWITCH_PEER[AUTHENTICATOR],
        verbose=verbose,
    )
    probe_inter_switch_ping(
        supp_container,
        SUPPLICANT,
        INTER_SWITCH_PEER[SUPPLICANT],
        verbose=verbose,
    )

    if verify_reauth:
        check_dot1x_reauth_cycle(
            targets,
            auth_container,
            supp_container,
            auth_ckn,
            verbose=verbose,
        )

    print()
    run_quadra_macsec_checks(
        auth_container,
        quadra_slave_container,
        skip_config=skip_config,
        verbose=verbose,
    )

    checks = "[config] and [live] checks" if not skip_config else "live checks only"
    reauth_note = ", reauth cycle" if verify_reauth else ""
    report_summary(
        "MACsec",
        f"all {checks}{reauth_note} passed "
        "(802.1X EAP-TLS + QuaDRA static MACsec, encrypted traffic)",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify dynamic MACsec (802.1X EAP-TLS + MKA) on the inter-switch link.",
    )
    parser.add_argument("--clab-name", default=LAB_NAME)
    parser.add_argument("--mgmt-subnet", default="172.20.127.0/24")
    parser.add_argument(
        "--skip-config",
        action="store_true",
        help="Skip EOS running-config checks (live state only)",
    )
    parser.add_argument(
        "--verify-reauth",
        action="store_true",
        help=(
            "After baseline checks, wait for periodic 802.1X reauth and verify "
            "Authorized state, stable CKN, and RADIUS Login OK (also VERIFY_REAUTH=1)"
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Echo commands and print full output (also enabled by VERBOSE=1)",
    )
    args = parser.parse_args(argv)
    verbose = args.verbose or os.environ.get("VERBOSE") == "1"
    verify_reauth = args.verify_reauth or os.environ.get("VERIFY_REAUTH") == "1"

    try:
        run_macsec_checks(
            clab_name=args.clab_name,
            mgmt_subnet=args.mgmt_subnet,
            skip_config=args.skip_config,
            verify_reauth=verify_reauth,
            verbose=verbose,
        )
    except (MacsecCheckError, subprocess.CalledProcessError) as exc:
        report_summary("MACsec", str(exc), CheckStatus.FAIL, file=sys.stderr)
        print(file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
