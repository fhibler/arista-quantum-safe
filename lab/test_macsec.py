"""Live lab checks for dynamic MACsec (802.1X EAP-TLS + MKA) on the inter-switch link."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

from lab.topology_contract import (
    CEOS_DATA_PLANE,
    DOT1X_EAP_IDENTITY,
    DOT1X_EAP_SSL_PROFILE,
    DOT1X_SUPPLICANT_PROFILE,
    MACSEC_PROFILE,
)
from lab.test_pqc_connections import LabTargets, assert_contains, ceos_cli

MACSEC_INTERFACE = "Ethernet1"
AUTHENTICATOR = "ceos1"
SUPPLICANT = "ceos2"
PQC_EAP_GROUP = "X25519MLKEM768"
INTER_SWITCH_PEER = {
    AUTHENTICATOR: CEOS_DATA_PLANE[SUPPLICANT]["eth1"].split("/")[0],
    SUPPLICANT: CEOS_DATA_PLANE[AUTHENTICATOR]["eth1"].split("/")[0],
}


class MacsecCheckError(RuntimeError):
    """Raised when a live MACsec/MKA check fails."""


def print_device(name: str) -> None:
    print(f"=== {name} ===")


def report_config(detail: str) -> None:
    print(f"  [config] {detail}")


def report_live(detail: str) -> None:
    print(f"  [live]   {detail}")


def extract_ckn(participants_output: str) -> str:
    match = re.search(r"CKN:\s+([0-9a-f]+)", participants_output, re.IGNORECASE)
    if not match:
        raise MacsecCheckError("expected CKN in mac security participants detail")
    return match.group(1)


def check_authenticator_config(container: str) -> None:
    cfg = ceos_cli(container, "enable\nshow running-config | section dot1x\n")
    if "aaa authentication dot1x default group" not in cfg.lower():
        raise MacsecCheckError(f"{AUTHENTICATOR} dot1x aaa: expected dot1x authentication group")
    intf = ceos_cli(container, f"enable\nshow running-config interface {MACSEC_INTERFACE}\n")
    assert_contains(intf, "dot1x pae authenticator", label=f"{AUTHENTICATOR} dot1x authenticator")
    assert_contains(intf, f"mac security profile {MACSEC_PROFILE}", label=f"{AUTHENTICATOR} macsec profile")
    report_config(
        f"dot1x authenticator, mac security profile {MACSEC_PROFILE}, RadSec AAA group RADIUS"
    )


def check_supplicant_config(container: str) -> None:
    cfg = ceos_cli(container, "enable\nshow running-config | section dot1x\n")
    assert_contains(cfg, f"supplicant profile {DOT1X_SUPPLICANT_PROFILE}", label=f"{SUPPLICANT} supplicant profile")
    assert_contains(cfg, f"identity {DOT1X_EAP_IDENTITY}", label=f"{SUPPLICANT} EAP identity")
    assert_contains(cfg, "eap-method tls", label=f"{SUPPLICANT} EAP-TLS")
    assert_contains(cfg, f"ssl profile {DOT1X_EAP_SSL_PROFILE}", label=f"{SUPPLICANT} DOT1X ssl profile")
    intf = ceos_cli(container, f"enable\nshow running-config interface {MACSEC_INTERFACE}\n")
    assert_contains(intf, f"dot1x pae supplicant {DOT1X_SUPPLICANT_PROFILE}", label=f"{SUPPLICANT} dot1x supplicant")
    report_config(
        f"dot1x supplicant {DOT1X_SUPPLICANT_PROFILE}, EAP-TLS + ssl profile {DOT1X_EAP_SSL_PROFILE}"
    )


def check_authenticator_dot1x(container: str) -> None:
    hosts = ceos_cli(container, "enable\nshow dot1x hosts\n")
    assert_contains(hosts, DOT1X_EAP_IDENTITY, label=f"{AUTHENTICATOR} dot1x host identity")
    assert_contains(hosts, "SUCCESS", label=f"{AUTHENTICATOR} dot1x host state")
    detail = ceos_cli(container, f"enable\nshow dot1x interface {MACSEC_INTERFACE} detail\n")
    assert_contains(detail, "Port status: Authorized", label=f"{AUTHENTICATOR} dot1x port authorized")
    report_live(f"802.1X host {DOT1X_EAP_IDENTITY} SUCCESS, port Authorized")


def check_supplicant_dot1x(container: str) -> None:
    output = ceos_cli(container, "enable\nshow dot1x supplicant\n")
    assert_contains(output, f"Identity: {DOT1X_EAP_IDENTITY}", label=f"{SUPPLICANT} dot1x identity")
    assert_contains(output, "Status: success", label=f"{SUPPLICANT} dot1x status")
    assert_contains(output, "EAP method: tls", label=f"{SUPPLICANT} EAP method")
    assert_contains(output, f"SSL profile: {DOT1X_EAP_SSL_PROFILE}", label=f"{SUPPLICANT} ssl profile")
    assert_contains(output, PQC_EAP_GROUP, label=f"{SUPPLICANT} EAP-TLS PQC group")
    report_live(f"802.1X supplicant success (EAP-TLS, {PQC_EAP_GROUP})")


def check_macsec_interface(container: str, node: str) -> None:
    output = ceos_cli(container, f"enable\nshow mac security interface {MACSEC_INTERFACE} detail\n")
    assert_contains(output, "Controlled port: True", label=f"{node} controlled port")
    assert_contains(output, "Traffic: encrypted", label=f"{node} traffic encrypted")
    if "Key in use: None" in output or "Key in use:" not in output:
        raise MacsecCheckError(f"{node}: expected active SAK (Key in use)")
    report_live(f"MACsec controlled port up, traffic encrypted on {MACSEC_INTERFACE}")


def check_mka_participants(container: str, node: str) -> str:
    output = ceos_cli(container, "enable\nshow mac security participants detail\n")
    assert_contains(output, "CKN:", label=f"{node} MKA participants")
    assert_contains(output, "Success: True", label=f"{node} MKA session success")
    assert_contains(output, "Live peer list:", label=f"{node} MKA live peers")
    if 'Live peer list: []' in output:
        raise MacsecCheckError(f"{node}: MKA live peer list is empty")
    ckn = extract_ckn(output)
    report_live(f"MKA participant CKN {ckn}, Success: True")
    return ckn


def probe_inter_switch_ping(container: str, node: str, peer_ip: str) -> None:
    output = ceos_cli(container, f"enable\nping {peer_ip} repeat 3\n")
    if "0% packet loss" not in output and "Success rate is 100 percent" not in output:
        raise MacsecCheckError(f"{node} ping {peer_ip} over MACsec link: no successful replies")
    report_live(f"ping {peer_ip} over encrypted {MACSEC_INTERFACE} (0% loss)")


def run_macsec_checks(
    *,
    clab_name: str,
    mgmt_subnet: str,
    skip_config: bool = False,
) -> None:
    from lab.topology_contract import mgmt_ips_for_subnet

    ips = mgmt_ips_for_subnet(mgmt_subnet)
    targets = LabTargets(
        clab_name=clab_name,
        radius_ip=ips["radius"],
        ceos_ips={AUTHENTICATOR: ips[AUTHENTICATOR], SUPPLICANT: ips[SUPPLICANT]},
    )
    auth_container = targets.ceos_container(AUTHENTICATOR)
    supp_container = targets.ceos_container(SUPPLICANT)

    print("MACsec verification (802.1X EAP-TLS + MKA on inter-switch link)")
    print("  [config] EOS running-config stanzas")
    print("  [live]   dot1x state, MKA participants, encrypted traffic, inter-switch ping\n")

    print_device(AUTHENTICATOR)
    if not skip_config:
        check_authenticator_config(auth_container)
    check_authenticator_dot1x(auth_container)
    check_macsec_interface(auth_container, AUTHENTICATOR)
    auth_ckn = check_mka_participants(auth_container, AUTHENTICATOR)

    print()
    print_device(SUPPLICANT)
    if not skip_config:
        check_supplicant_config(supp_container)
    check_supplicant_dot1x(supp_container)
    check_macsec_interface(supp_container, SUPPLICANT)
    supp_ckn = check_mka_participants(supp_container, SUPPLICANT)

    if auth_ckn != supp_ckn:
        raise MacsecCheckError(
            f"CKN mismatch: {AUTHENTICATOR}={auth_ckn!r} vs {SUPPLICANT}={supp_ckn!r}"
        )
    report_live(f"matching CKN on both peers ({auth_ckn})")

    print()
    print_device("inter-switch")
    probe_inter_switch_ping(auth_container, AUTHENTICATOR, INTER_SWITCH_PEER[AUTHENTICATOR])
    probe_inter_switch_ping(supp_container, SUPPLICANT, INTER_SWITCH_PEER[SUPPLICANT])

    scope = "live checks only" if skip_config else "[config] and [live] checks"
    print(f"\nMACsec: OK — all {scope} passed (802.1X EAP-TLS, MKA, encrypted traffic)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify dynamic MACsec (802.1X EAP-TLS + MKA) on the inter-switch link.",
    )
    parser.add_argument("--clab-name", default="qkd-macsec-radius")
    parser.add_argument("--mgmt-subnet", default="172.20.127.0/24")
    parser.add_argument(
        "--skip-config",
        action="store_true",
        help="Skip EOS running-config checks (live state only)",
    )
    args = parser.parse_args(argv)

    try:
        run_macsec_checks(
            clab_name=args.clab_name,
            mgmt_subnet=args.mgmt_subnet,
            skip_config=args.skip_config,
        )
    except (MacsecCheckError, subprocess.CalledProcessError) as exc:
        print(f"\nMACsec: FAIL — {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
