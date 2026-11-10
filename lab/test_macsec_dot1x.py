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
from lab.report import CheckStatus, print_device, print_section_header, print_test_header, report_ok, report_check_summary, report_summary, reset_check_stats
from lab.topology_contract import (
    CEOS_DATA_PLANE,
    DOT1X_EAP_IDENTITY,
    DOT1X_EAP_SSL_PROFILE,
    DOT1X_REAUTH_PERIOD_SEC,
    DOT1X_SUPPLICANT_PROFILE,
    LAB_NAME,
    MACSEC_PROFILE,
)
from lab.test_pqc_connections import LabTargets, ceos_cli, ceos_show_json, docker_exec
from lab.report import report_wait

MACSEC_INTERFACE = "Ethernet1"
AUTHENTICATOR = "ceos1-both"
SUPPLICANT = "ceos2-pqc"
PQC_EAP_GROUP = "X25519MLKEM768"
INTER_SWITCH_PEER = {
    AUTHENTICATOR: CEOS_DATA_PLANE[SUPPLICANT]["eth1"].split("/")[0],
    SUPPLICANT: CEOS_DATA_PLANE[AUTHENTICATOR]["eth1"].split("/")[0],
}
REAUTH_WAIT_BUFFER_SEC = 15
MKA_POLL_INTERVAL_SEC = 2
MKA_POLL_ATTEMPTS = 15


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


def _read_mka_ckn(container: str, node: str, *, verbose: bool | None = None) -> str:
    """Read one successful MKA participant snapshot with live peers."""
    output = ceos_show_json(container, "show mac security participants detail", verbose=verbose)
    if not json_truthy(output, "success") and not json_tree_contains(
        output, "Success", case_sensitive=False
    ):
        raise MacsecCheckError(f"{node}: expected successful MKA participant")
    if not mka_has_live_peers(output):
        raise MacsecCheckError(f"{node}: MKA live peer list is empty")
    try:
        return extract_ckn_from_json(output)
    except CeosJsonError as exc:
        raise MacsecCheckError(f"{node}: {exc}") from exc


def check_mka_participants(container: str, node: str, *, verbose: bool | None = None) -> str:
    """Poll MKA participants until live peers appear (802.1X reauth can briefly clear them)."""
    last_error: str | None = None
    report_wait(
        f"{node} MKA live peers", maximum_sec=(MKA_POLL_ATTEMPTS - 1) * MKA_POLL_INTERVAL_SEC,
        detail=f"retry delays; {MKA_POLL_ATTEMPTS} attempts, {MKA_POLL_INTERVAL_SEC}s apart; command time extra",
    )
    for attempt in range(MKA_POLL_ATTEMPTS):
        if attempt:
            time.sleep(MKA_POLL_INTERVAL_SEC)
        try:
            ckn = _read_mka_ckn(container, node, verbose=verbose)
        except MacsecCheckError as exc:
            last_error = str(exc)
            continue
        report_live(f"MKA participant CKN {ckn}, Success: True")
        return ckn
    raise MacsecCheckError(last_error or f"{node}: MKA participants check failed")


def check_matching_mka_ckn(
    auth_container: str,
    supp_container: str,
    *,
    verbose: bool | None = None,
) -> str:
    """Resample both peers until their principal CKNs agree across reauth."""
    last_error = "MKA peer CKN check failed"
    report_wait(
        "matching MKA CKN on both peers", maximum_sec=(MKA_POLL_ATTEMPTS - 1) * MKA_POLL_INTERVAL_SEC,
        detail=f"retry delays; {MKA_POLL_ATTEMPTS} paired attempts, {MKA_POLL_INTERVAL_SEC}s apart; command time extra",
    )
    for attempt in range(MKA_POLL_ATTEMPTS):
        if attempt:
            time.sleep(MKA_POLL_INTERVAL_SEC)
        try:
            auth_ckn = _read_mka_ckn(auth_container, AUTHENTICATOR, verbose=verbose)
            supp_ckn = _read_mka_ckn(supp_container, SUPPLICANT, verbose=verbose)
        except MacsecCheckError as exc:
            last_error = str(exc)
            continue
        if auth_ckn != supp_ckn:
            last_error = (
                f"CKN mismatch: {AUTHENTICATOR}={auth_ckn!r} vs {SUPPLICANT}={supp_ckn!r}"
            )
            continue
        report_live(f"MKA participants successful with live peers, matching CKN on both peers ({auth_ckn})")
        return auth_ckn
    raise MacsecCheckError(f"{last_error} (after {MKA_POLL_ATTEMPTS} paired MKA attempts)")


def count_radius_login_ok(radius_container: str, *, verbose: bool | None = None) -> int:
    result = docker_exec(
        radius_container,
        r"grep -Ec 'Auth: (\([0-9]+\) )?Login OK' /var/log/radius/radius.log 2>/dev/null || true",
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
    print_section_header("=== periodic 802.1X reauthentication ===")
    report_wait(
        "periodic 802.1X reauthentication",
        expected_sec=wait_sec, maximum_sec=wait_sec + (MKA_POLL_ATTEMPTS - 1) * MKA_POLL_INTERVAL_SEC,
        detail=f"{wait_sec}s fixed wait plus MKA retry delays; command time extra",
    )
    time.sleep(wait_sec)

    check_authenticator_dot1x(auth_container, verbose=verbose)
    check_supplicant_dot1x(supp_container, verbose=verbose)

    # Each EAP-TLS reauth derives a new MSK / EAP-Session-Id, so CKN often
    # rotates. That is expected; peers must still agree on the live CA.
    auth_ckn = check_matching_mka_ckn(auth_container, supp_container, verbose=verbose)

    after_ok = count_radius_login_ok(targets.radius_container, verbose=verbose)
    if after_ok <= baseline_ok:
        raise MacsecCheckError(
            f"expected additional RADIUS Login OK after {wait_sec}s reauth wait "
            f"(baseline {baseline_ok}, after {after_ok})"
        )
    if auth_ckn == baseline_ckn:
        ckn_note = f"CKN unchanged ({auth_ckn})"
    else:
        ckn_note = f"CKN rotated {baseline_ckn} → {auth_ckn} (peers match)"
    report_live(
        f"802.1X reauth cycle OK - port Authorized, {ckn_note}, "
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


def run_macsec_checks(
    *,
    clab_name: str,
    mgmt_subnet: str,
    skip_config: bool = False,
    verify_reauth: bool = False,
    verbose: bool | None = None,
) -> None:
    reset_check_stats()
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

    print_test_header(
        "MACsec verification (802.1X EAP-TLS + MKA on inter-switch link)",
        "  [config] EOS running-config stanzas",
        "  [live]   dot1x state, MKA participants, encrypted traffic, inter-switch ping",
    )

    print_device(AUTHENTICATOR)
    if not skip_config:
        check_authenticator_config(auth_container, verbose=verbose)
    check_authenticator_dot1x(auth_container, verbose=verbose)
    check_macsec_interface(auth_container, AUTHENTICATOR, verbose=verbose)

    print()
    print_device(SUPPLICANT)
    if not skip_config:
        check_supplicant_config(supp_container, verbose=verbose)
    check_supplicant_dot1x(supp_container, verbose=verbose)
    check_macsec_interface(supp_container, SUPPLICANT, verbose=verbose)

    print()
    print_device("inter-switch")
    # Keep peer reads adjacent, then resample both if periodic reauth rotates
    # the CKN between reads or EOS has not switched both principal actors yet.
    auth_ckn = check_matching_mka_ckn(auth_container, supp_container, verbose=verbose)
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

    report_check_summary("MACsec")


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
            "Authorized state, matching CKN (rotation allowed), and RADIUS Login OK "
            "(also VERIFY_REAUTH=1)"
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
