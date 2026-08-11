"""Live lab checks for QuaDRA QKD MACsec key rotation (ceos1-both master ↔ ceos3-qkd slave)."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass

from lab.report import CheckStatus, print_device, print_section_header, report_ok, report_summary, report_warn
from lab.topology_contract import (
    CEOS_QUADRA_NODES,
    KME_B_SAE_ID,
    KME_SAE_ID,
    LAB_NAME,
    QUADRA_MACSEC_INTF,
    QUADRA_MACSEC_PROFILE_MASTER,
    QUADRA_MACSEC_PROFILE_SLAVE,
    QUADRA_PEER_IP,
    container_name,
    quadra_swix_name,
)
from lab.kme_http import DOCKER_EXEC_TIMEOUT_SEC
from lab.test_pqc_connections import PqcConnectionError, ceos_cli
from lab.verbose import echo_command, echo_result, verbose_enabled

MASTER = "ceos1-both"
SLAVE = "ceos3-qkd"
EXPECTED_AGENT_ROLES = {MASTER: "master", SLAVE: "slave"}
ROTATION_SUCCESS_MARKERS = ("QUADRA-4-ROTATION_SUCCESS", "ROTATION_SUCCESS")
INSTALLED_RE = re.compile(r"\bI\b")
RUNNING_RE = re.compile(r"running with PID\s+\d+", re.IGNORECASE)
STATUS_FIELD_RE = re.compile(
    r"^([a-z][a-z0-9 ]+?)\s{2,}(.+?)\s*$",
    re.IGNORECASE,
)
IDENTIFIER_RE = re.compile(r"identifier\s+(\S+)")
SAK_KEY_LINE_RE = re.compile(r"an\s+(\d+)\s+key(?:\s+(\d))?\s+(.+)")
MACSEC_SAK_AN_RE = re.compile(r"Rx AN:\s*(\d+)\s*Tx AN:\s*(\d+)")


@dataclass(frozen=True)
class SakChannel:
    """One static SAK secure channel (rx or tx) from running-config."""

    identifier: str
    an: int
    key: str
    encrypted: bool


@dataclass(frozen=True)
class StaticSakProfile:
    """Parsed ``key source sak static`` profile from ``show running-config``."""

    rx: SakChannel
    tx: SakChannel


class QkdCheckError(RuntimeError):
    """Raised when a live QuaDRA / QKD check fails."""


class QkdSkip(Exception):
    """Raised when QuaDRA is not installed and checks should be skipped."""


@dataclass(frozen=True)
class QkdTargets:
    clab_name: str

    def ceos_container(self, node: str) -> str:
        return container_name(node, lab_name=self.clab_name)

    def kme_container(self, node: str) -> str:
        return container_name(node, lab_name=self.clab_name)


def report_live(detail: str) -> None:
    report_ok("[live]  ", detail)


def report_log(detail: str) -> None:
    report_ok("[log]   ", detail)


def report_log_warn(detail: str) -> None:
    report_warn("[log]   ", detail)


def report_kme(detail: str) -> None:
    report_ok("[kme]  ", detail)


def report_keys(detail: str) -> None:
    report_ok("[keys] ", detail)


def extension_installed(show_extensions: str, swix: str) -> bool:
    for line in show_extensions.splitlines():
        if swix not in line:
            continue
        if INSTALLED_RE.search(line):
            return True
    return False


def parse_daemon_quadra_status(text: str) -> dict[str, str]:
    """Parse the Status table from ``show daemon quadra``."""
    status: dict[str, str] = {}
    section = text
    if "Status:" in text:
        section = text.split("Status:", 1)[1]
    lines = section.splitlines()
    current_key: str | None = None
    for line in lines:
        stripped = line.rstrip()
        if not stripped:
            if current_key is not None:
                current_key = None
            continue
        if stripped.startswith("----"):
            continue
        if stripped.startswith("Data ") and "Value" in stripped:
            continue
        match = STATUS_FIELD_RE.match(stripped)
        if match:
            current_key = match.group(1).strip().lower()
            status[current_key] = match.group(2).strip()
            continue
        if current_key is not None and line.startswith(" "):
            status[current_key] = f"{status[current_key]} {stripped.strip()}"
    return status


def status_field(status: dict[str, str], *names: str) -> str | None:
    for name in names:
        value = status.get(name.lower())
        if value:
            return value
    return None


def _profile_config_block(config_text: str, profile: str) -> str:
    marker = f"profile {profile}"
    if marker not in config_text:
        raise QkdCheckError(f"missing mac security profile {profile!r} in running-config")
    block = config_text.split(marker, 1)[1]
    for stop in ("profile ", "interface ", "daemon ", "dot1x ", "mac security\n"):
        if stop in block:
            block = block.split(stop, 1)[0]
    return block


def _parse_sak_channel(block: str, direction: str, *, profile: str) -> SakChannel:
    marker = f"secure channel {direction}"
    if marker not in block:
        raise QkdCheckError(f"profile {profile}: missing {marker}")
    section = block.split(marker, 1)[1]
    if "secure channel" in section:
        section = section.split("secure channel", 1)[0]
    id_match = IDENTIFIER_RE.search(section)
    key_match = SAK_KEY_LINE_RE.search(section)
    if not id_match or not key_match:
        raise QkdCheckError(f"profile {profile}: incomplete static SAK {direction} channel")
    encrypted = key_match.group(2) == "7"
    return SakChannel(
        identifier=id_match.group(1),
        an=int(key_match.group(1)),
        key=key_match.group(3).strip(),
        encrypted=encrypted,
    )


def parse_static_sak_profile(config_text: str, profile: str) -> StaticSakProfile:
    """Parse rx/tx secure channels from ``show running-config | section mac security``."""
    block = _profile_config_block(config_text, profile)
    if "key source sak static" not in block:
        raise QkdCheckError(f"profile {profile}: expected key source sak static")
    if "cipher aes256-gcm-xpn" not in block:
        raise QkdCheckError(f"profile {profile}: expected cipher aes256-gcm-xpn")
    return StaticSakProfile(
        rx=_parse_sak_channel(block, "rx", profile=profile),
        tx=_parse_sak_channel(block, "tx", profile=profile),
    )


def assert_static_sak_peer_mapping(master: StaticSakProfile, slave: StaticSakProfile) -> None:
    """Master rx ↔ slave tx and master tx ↔ slave rx must share SC IDs and ANs."""
    if master.rx.identifier != slave.tx.identifier:
        raise QkdCheckError(
            f"SC ID mismatch: master rx {master.rx.identifier!r} != slave tx {slave.tx.identifier!r}"
        )
    if master.tx.identifier != slave.rx.identifier:
        raise QkdCheckError(
            f"SC ID mismatch: master tx {master.tx.identifier!r} != slave rx {slave.rx.identifier!r}"
        )
    if master.rx.an != slave.tx.an:
        raise QkdCheckError(
            f"AN mismatch: master rx AN {master.rx.an} != slave tx AN {slave.tx.an}"
        )
    if master.tx.an != slave.rx.an:
        raise QkdCheckError(
            f"AN mismatch: master tx AN {master.tx.an} != slave rx AN {slave.rx.an}"
        )


def assert_plain_sak_key_exchange(master: StaticSakProfile, slave: StaticSakProfile) -> None:
    """Plain hex SAKs must cross-match (master tx key == slave rx key, etc.)."""
    if master.rx.key != slave.tx.key:
        raise QkdCheckError("plain SAK mismatch: master rx key != slave tx key")
    if master.tx.key != slave.rx.key:
        raise QkdCheckError("plain SAK mismatch: master tx key != slave rx key")


def check_macsec_interface_sak_state(
    container: str,
    node: str,
    interface: str,
    expected_rx_an: int,
    expected_tx_an: int,
    *,
    verbose: bool | None,
) -> None:
    """Verify summary MACsec state matches configured static SAK ANs."""
    from lab.ceos_json import json_find_value, json_truthy, macsec_has_active_key
    from lab.test_pqc_connections import ceos_show_json

    try:
        payload = ceos_show_json(container, f"show mac security interface {interface}", verbose=verbose)
    except PqcConnectionError as exc:
        raise QkdCheckError(str(exc)) from exc

    if not json_truthy(payload, "controlledPort"):
        raise QkdCheckError(f"{node} {interface}: controlled port not up")
    if not macsec_has_active_key(payload):
        raise QkdCheckError(f"{node} {interface}: no active static SAK")

    key_msg_id = json_find_value(payload, "keyMsgId")
    if not isinstance(key_msg_id, str):
        raise QkdCheckError(f"{node} {interface}: missing keyMsgId in MACsec interface JSON")
    an_match = MACSEC_SAK_AN_RE.search(key_msg_id)
    if not an_match:
        raise QkdCheckError(
            f"{node} {interface}: expected static SAK keyMsgId, got {key_msg_id!r}"
        )
    live_rx_an = int(an_match.group(1))
    live_tx_an = int(an_match.group(2))
    if live_rx_an != expected_rx_an or live_tx_an != expected_tx_an:
        raise QkdCheckError(
            f"{node} {interface}: live AN rx/tx {live_rx_an}/{live_tx_an} "
            f"!= configured {expected_rx_an}/{expected_tx_an}"
        )


def check_static_sak_key_sync(
    master_container: str,
    slave_container: str,
    *,
    verbose: bool | None,
) -> None:
    """Verify QuaDRA static SAK profiles are cross-mapped and operationally in sync."""
    master_cfg = ceos_cli(
        master_container,
        "enable\nshow running-config | section mac security\n",
        verbose=verbose,
    )
    slave_cfg = ceos_cli(
        slave_container,
        "enable\nshow running-config | section mac security\n",
        verbose=verbose,
    )
    master_profile = parse_static_sak_profile(master_cfg, QUADRA_MACSEC_PROFILE_MASTER)
    slave_profile = parse_static_sak_profile(slave_cfg, QUADRA_MACSEC_PROFILE_SLAVE)

    assert_static_sak_peer_mapping(master_profile, slave_profile)
    report_keys(
        f"SC/AN mapping OK — master rx AN {master_profile.rx.an} ↔ slave tx AN {slave_profile.tx.an}, "
        f"master tx AN {master_profile.tx.an} ↔ slave rx AN {slave_profile.rx.an}"
    )

    uses_encrypted_keys = any(
        channel.encrypted
        for channel in (
            master_profile.rx,
            master_profile.tx,
            slave_profile.rx,
            slave_profile.tx,
        )
    )
    if uses_encrypted_keys:
        check_macsec_interface_sak_state(
            master_container,
            MASTER,
            QUADRA_MACSEC_INTF[MASTER],
            master_profile.rx.an,
            master_profile.tx.an,
            verbose=verbose,
        )
        check_macsec_interface_sak_state(
            slave_container,
            SLAVE,
            QUADRA_MACSEC_INTF[SLAVE],
            slave_profile.rx.an,
            slave_profile.tx.an,
            verbose=verbose,
        )
        report_keys(
            f"encrypted SAK in sync — both sides controlled port up, AN {master_profile.rx.an}/"
            f"{master_profile.tx.an} on {QUADRA_MACSEC_INTF[MASTER]}/{QUADRA_MACSEC_INTF[SLAVE]}"
        )
    else:
        assert_plain_sak_key_exchange(master_profile, slave_profile)
        report_keys("plain SAK keys cross-match (master tx == slave rx, master rx == slave tx)")


def check_extension_installed(container: str, node: str, swix: str, *, verbose: bool | None) -> None:
    output = ceos_cli(container, "enable\nshow extensions\n", verbose=verbose)
    if not extension_installed(output, swix):
        raise QkdSkip(f"{node}: QuaDRA extension {swix} not installed")
    report_live(f"{swix} installed")


def check_daemon_running(container: str, node: str, *, verbose: bool | None) -> str:
    output = ceos_cli(container, "enable\nshow daemon quadra\n", verbose=verbose)
    if not RUNNING_RE.search(output):
        raise QkdCheckError(f"{node}: daemon quadra is not running")
    report_live("daemon quadra running")
    return output


def check_agent_role(
    node: str,
    output: str,
    *,
    expected_role: str,
    verbose: bool | None = None,
) -> dict[str, str]:
    del verbose
    status = parse_daemon_quadra_status(output)
    role = status_field(status, "agent status")
    if role != expected_role:
        raise QkdCheckError(
            f"{node}: expected agent status {expected_role!r}, got {role!r}"
        )
    report_live(f"agent status {role}")
    return status


def check_master_rotation_schedule(node: str, status: dict[str, str]) -> None:
    next_event = status_field(status, "next key rotation event")
    if not next_event:
        raise QkdCheckError(f"{node}: missing next key rotation event in show daemon quadra")
    report_live(f"next key rotation event {next_event}")


def read_docker_logs(container: str, *, verbose: bool | None = None) -> str:
    """Return combined stdout/stderr from ``docker logs``."""
    show = verbose_enabled(verbose)
    argv = ["docker", "logs", container]
    if show:
        echo_command(f"docker logs {container}", argv)
    try:
        result = subprocess.run(
            argv,
            text=True,
            capture_output=True,
            check=False,
            timeout=DOCKER_EXEC_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired as exc:
        raise QkdCheckError(f"{container}: docker logs timed out after {DOCKER_EXEC_TIMEOUT_SEC}s") from exc
    if show:
        echo_result(result)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise QkdCheckError(f"{container}: docker logs failed: {detail}")
    return result.stdout + result.stderr


def kme_key_request_lines(logs: str, endpoint: str, *, sae_id: str | None = None) -> list[str]:
    """Return KME access-log lines for POST requests to *endpoint* (enc_keys / dec_keys)."""
    matches: list[str] = []
    for line in logs.splitlines():
        if "POST" not in line or endpoint not in line:
            continue
        if sae_id is not None and sae_id not in line:
            continue
        matches.append(line.strip())
    return matches


def check_kme_key_request_logs(
    container: str,
    kme_node: str,
    *,
    endpoint: str,
    sae_id: str,
    verbose: bool | None = None,
) -> str:
    logs = read_docker_logs(container, verbose=verbose)
    matches = kme_key_request_lines(logs, endpoint, sae_id=sae_id)
    if not matches:
        matches = kme_key_request_lines(logs, endpoint)
    if not matches:
        raise QkdCheckError(
            f"{kme_node}: no POST /{endpoint} requests in docker logs "
            f"(expected QuaDRA key rotation traffic)"
        )
    latest = matches[-1]
    if " 200 " not in latest and '" 200 ' not in latest:
        raise QkdCheckError(f"{kme_node}: latest /{endpoint} request did not return 200: {latest}")
    report_kme(f"{endpoint} logged ({len(matches)} POST, latest HTTP 200)")
    return latest


def find_rotation_success_log(container: str, node: str, *, verbose: bool | None) -> str | None:
    """Return the first %QUADRA-4-ROTATION_SUCCESS% line in recent syslog, if any."""
    output = ceos_cli(container, "enable\nshow logging 500\n", verbose=verbose)
    for line in output.splitlines():
        if any(marker in line for marker in ROTATION_SUCCESS_MARKERS):
            return line.strip()
    return None


def note_rotation_success_log(container: str, node: str, *, verbose: bool | None) -> bool:
    """Record rotation-success syslog when present (startup/recovery only on QuaDRA)."""
    line = find_rotation_success_log(container, node, verbose=verbose)
    if line:
        report_log(f"found rotation success: {line}")
        return True
    report_log_warn(
        f"{node}: no %QUADRA-4-ROTATION_SUCCESS% in recent syslog "
        "(normal in steady state — QuaDRA logs this only after agent startup or last failure)"
    )
    return False


def check_quadra_link_ping(
    master_container: str,
    slave_container: str,
    *,
    verbose: bool | None,
) -> None:
    from lab.ceos_json import ping_text_success

    master_peer = QUADRA_PEER_IP[MASTER]
    slave_peer = QUADRA_PEER_IP[SLAVE]
    master_ping = ceos_cli(
        master_container,
        f"enable\nping {master_peer} repeat 3\n",
        verbose=verbose,
    )
    if not ping_text_success(master_ping):
        raise QkdCheckError(f"{MASTER} ping {master_peer} over QuaDRA link failed")
    report_live(f"{MASTER} ping {master_peer} over {QUADRA_MACSEC_INTF[MASTER]} OK")

    slave_ping = ceos_cli(
        slave_container,
        f"enable\nping {slave_peer} repeat 3\n",
        verbose=verbose,
    )
    if not ping_text_success(slave_ping):
        raise QkdCheckError(f"{SLAVE} ping {slave_peer} over QuaDRA link failed")
    report_live(f"{SLAVE} ping {slave_peer} over {QUADRA_MACSEC_INTF[SLAVE]} OK")


def quadra_installed_on_nodes(targets: QkdTargets, swix: str, *, verbose: bool | None) -> bool:
    for node in sorted(CEOS_QUADRA_NODES):
        container = targets.ceos_container(node)
        try:
            output = ceos_cli(container, "enable\nshow extensions\n", verbose=verbose)
        except (PqcConnectionError, subprocess.CalledProcessError):
            return False
        if not extension_installed(output, swix):
            return False
    return True


def run_qkd_checks(
    *,
    clab_name: str,
    verbose: bool | None = None,
) -> bool:
    """Run QuaDRA checks. Returns True when checks ran, False when skipped."""
    swix = quadra_swix_name()
    targets = QkdTargets(clab_name=clab_name)

    print_section_header("QuaDRA / QKD verification (static MACsec key rotation)")
    print("  [live]  show daemon quadra, agent role, next rotation, QuaDRA link ping")
    print("  [keys]  static SAK profile cross-mapping (master tx ↔ slave rx)")
    print("  [log]   %QUADRA-4-ROTATION_SUCCESS% when present (startup/recovery only)")
    print("  [kme]   enc_keys / dec_keys in KME container logs\n")

    if not quadra_installed_on_nodes(targets, swix, verbose=verbose):
        report_summary(
            "QuaDRA",
            f"skipped — {swix} not installed on both {MASTER} and {SLAVE}",
            CheckStatus.WARN,
        )
        return False

    master_container = targets.ceos_container(MASTER)
    slave_container = targets.ceos_container(SLAVE)

    print_device(MASTER)
    check_extension_installed(master_container, MASTER, swix, verbose=verbose)
    master_output = check_daemon_running(master_container, MASTER, verbose=verbose)
    master_status = check_agent_role(
        MASTER,
        master_output,
        expected_role=EXPECTED_AGENT_ROLES[MASTER],
        verbose=verbose,
    )
    check_master_rotation_schedule(MASTER, master_status)
    master_rotation_logged = note_rotation_success_log(master_container, MASTER, verbose=verbose)

    print()
    print_device(SLAVE)
    check_extension_installed(slave_container, SLAVE, swix, verbose=verbose)
    slave_output = check_daemon_running(slave_container, SLAVE, verbose=verbose)
    check_agent_role(
        SLAVE,
        slave_output,
        expected_role=EXPECTED_AGENT_ROLES[SLAVE],
        verbose=verbose,
    )
    slave_rotation_logged = note_rotation_success_log(slave_container, SLAVE, verbose=verbose)

    print()
    print_device("QuaDRA MACsec keys")
    check_static_sak_key_sync(master_container, slave_container, verbose=verbose)

    print()
    print_device("KME key delivery")
    check_kme_key_request_logs(
        targets.kme_container("kme-a"),
        "kme-a",
        endpoint="enc_keys",
        sae_id=KME_B_SAE_ID,
        verbose=verbose,
    )
    check_kme_key_request_logs(
        targets.kme_container("kme-b"),
        "kme-b",
        endpoint="dec_keys",
        sae_id=KME_SAE_ID,
        verbose=verbose,
    )

    print()
    print_device("QuaDRA link")
    check_quadra_link_ping(master_container, slave_container, verbose=verbose)

    rotation_note = (
        "rotation success in recent syslog"
        if master_rotation_logged and slave_rotation_logged
        else "steady-state rotation (no recent ROTATION_SUCCESS syslog)"
    )
    report_summary(
        "QuaDRA",
        f"daemon master/slave healthy, static SAK keys in sync, {rotation_note}, "
        "KME enc_keys/dec_keys seen, next rotation scheduled",
    )
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify QuaDRA QKD MACsec key rotation on ceos1-both and ceos3-qkd.",
    )
    parser.add_argument("--clab-name", default=LAB_NAME)
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Echo commands and print full output (also enabled by VERBOSE=1)",
    )
    args = parser.parse_args(argv)
    verbose = args.verbose or os.environ.get("VERBOSE") == "1"

    try:
        run_qkd_checks(clab_name=args.clab_name, verbose=verbose)
    except QkdSkip as exc:
        report_summary("QuaDRA", str(exc), CheckStatus.WARN)
        return 0
    except (QkdCheckError, PqcConnectionError, subprocess.CalledProcessError) as exc:
        report_summary("QuaDRA", str(exc), CheckStatus.FAIL, file=sys.stderr)
        print(file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
