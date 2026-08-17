"""Shared syslog-over-TLS PQC checks for live lab verification."""

from __future__ import annotations

import os
import pwd
import re
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from lab.ceos_json import json_tree_contains, json_truthy
from lab.probe_client import probe_syslog_ca_path, run_openssl_s_client
from lab.topology_contract import LAB_NAME, SYSLOG_PORT, SYSLOG_SSL_PROFILE, hostport
from lab.verbose import echo_command, verbose_enabled

PQC_GROUP = "X25519MLKEM768"
OPENSSL_PQC_CNF = "/etc/syslog-ng/openssl-pqc.cnf"
SYSLOG_LOG_PATH = "/var/log/syslog/eos.log"
PROBE_MESSAGE = "quantum-safe-syslog-probe"
CEOS_SYSLOG_NODES = ("ceos1-both", "ceos2-pqc", "ceos3-qkd")
MGMT_BRIDGE_NETWORK = "quantum-safe-mgmt"
DEFAULT_MGMT_BRIDGE = "mgmt-bridge"

# TLS 1.3 key_share group IDs (wire format)
TLS_KEY_SHARE_X25519 = 29
TLS_KEY_SHARE_SECP256R1 = 23
TLS_KEY_SHARE_X25519MLKEM768 = 4588

CLEARTEXT_SYSLOG_UDP_PORTS = (514, 601)
CLEARTEXT_SYSLOG_TCP_PORTS = (514,)

_sudo_tcpdump_required: bool | None = None
_sudo_capture_announced: bool = False


class SyslogCheckError(RuntimeError):
    """Raised when a syslog PQC or encryption check fails."""


def tls_key_share_group_name(group_id: int) -> str:
    """Map a TLS key_share group id from tshark to a readable name."""
    return {
        TLS_KEY_SHARE_X25519: "x25519",
        TLS_KEY_SHARE_SECP256R1: "secp256r1",
        TLS_KEY_SHARE_X25519MLKEM768: PQC_GROUP,
    }.get(group_id, f"gid:{group_id}")


def is_pqc_hybrid_key_share_group(group_id: int) -> bool:
    return group_id == TLS_KEY_SHARE_X25519MLKEM768


def resolve_mgmt_bridge() -> str | None:
    """Return the Containerlab mgmt bridge name when tcpdump can attach to it."""
    if not _command_exists("tcpdump"):
        return None
    result = subprocess.run(
        [
            "docker",
            "network",
            "inspect",
            MGMT_BRIDGE_NETWORK,
            "--format",
            '{{(index .Options "com.docker.network.bridge.name")}}',
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    bridge = result.stdout.strip()
    if bridge and result.returncode == 0 and Path(f"/sys/class/net/{bridge}").exists():
        return bridge
    if Path(f"/sys/class/net/{DEFAULT_MGMT_BRIDGE}").exists():
        return DEFAULT_MGMT_BRIDGE
    return None


def _command_exists(name: str) -> bool:
    from shutil import which

    return which(name) is not None


def tshark_client_hello_filter(switch_ip: str) -> str:
    """Build a tshark display filter for a cEOS ClientHello to syslog-ng."""
    if ":" in switch_ip:
        return f"tls.handshake.type == 1 && ipv6.src == {switch_ip}"
    return (
        f"tls.handshake.type == 1 && "
        f"(ip.src == {switch_ip} || ipv6.src == ::ffff:{switch_ip})"
    )


def _tcpdump_permission_denied(stderr: str) -> bool:
    """Return True when tcpdump stderr indicates missing capture privileges."""
    lower = stderr.lower()
    return (
        "don't have permission" in lower
        or "operation not permitted" in lower
        or "permission denied" in lower
    )


def _announce_sudo_tcpdump_capture(iface: str) -> None:
    """Print a one-time note before the first sudo tcpdump wire KEX capture."""
    global _sudo_capture_announced
    if _sudo_capture_announced:
        return
    _sudo_capture_announced = True
    print(
        "  [live]   syslog wire KEX capture: unprivileged tcpdump denied on "
        f"{iface}; using sudo fallback (enter password if prompted)",
        flush=True,
    )


def _capture_drop_user() -> str:
    """Login name to drop tcpdump privileges to after opening the capture device."""
    return pwd.getpwuid(os.getuid()).pw_name


def _remove_pcap(pcap: Path, *, verbose: bool | None = None) -> None:
    """Remove a pcap file, using sudo when a prior root-owned capture left it behind."""
    show = verbose_enabled(verbose)
    try:
        pcap.unlink(missing_ok=True)
    except PermissionError:
        if not _command_exists("sudo"):
            raise
        argv = ["sudo", "rm", "-f", str(pcap)]
        if show:
            echo_command("syslog wire KEX pcap cleanup", argv)
        subprocess.run(
            argv,
            check=False,
            stdin=None,
            stdout=subprocess.DEVNULL,
            stderr=None if show else subprocess.DEVNULL,
        )


def _tcpdump_argv(iface: str, pcap: Path, bpf_filter: str, *, use_sudo: bool) -> list[str]:
    cmd = [
        "tcpdump",
        "-i",
        iface,
        "-n",
        "-s",
        "0",
        "-w",
        str(pcap),
    ]
    if use_sudo:
        cmd.extend(["-Z", _capture_drop_user()])
    cmd.append(bpf_filter)
    if use_sudo:
        return ["sudo", *cmd]
    return cmd


def _run_bridge_tcpdump_capture(
    *,
    iface: str,
    pcap: Path,
    bpf_filter: str,
    bounce_logging: Callable[[], None],
    settle_sec: float,
    use_sudo: bool,
    verbose: bool | None = None,
) -> tuple[bool, str]:
    """Capture on a bridge interface; return (pcap_ok, tcpdump_stderr)."""
    show = verbose_enabled(verbose)
    _remove_pcap(pcap, verbose=verbose)
    argv = _tcpdump_argv(iface, pcap, bpf_filter, use_sudo=use_sudo)
    if show:
        echo_command("syslog wire KEX tcpdump", argv)

    popen_kwargs: dict[str, Any] = {"stdout": subprocess.DEVNULL}
    if use_sudo:
        # stdin stays inherited so sudo can prompt on the controlling terminal.
        popen_kwargs["stdin"] = None
        popen_kwargs["stderr"] = None if show else subprocess.DEVNULL
    else:
        popen_kwargs["stdin"] = subprocess.DEVNULL
        popen_kwargs["stderr"] = None if show else subprocess.PIPE

    tcpdump = subprocess.Popen(argv, **popen_kwargs)
    stderr = ""
    try:
        time.sleep(0.5)
        bounce_logging()
        time.sleep(settle_sec)
    finally:
        tcpdump.terminate()
        try:
            tcpdump.wait(timeout=5)
        except subprocess.TimeoutExpired:
            tcpdump.kill()
            tcpdump.wait(timeout=2)
        if not use_sudo and tcpdump.stderr is not None:
            stderr = tcpdump.stderr.read().decode(errors="replace")

    pcap_ok = pcap.exists() and pcap.stat().st_size >= 50
    if use_sudo and not pcap_ok and show:
        print(
            "  [live]   syslog wire KEX capture: sudo tcpdump did not capture "
            "a usable ClientHello",
            file=sys.stderr,
        )
    return pcap_ok, stderr


def _run_syslog_eth0_tcpdump_capture(
    *,
    syslog_container: str,
    container_pcap: str,
    bpf_filter: str,
    bounce_logging: Callable[[], None],
    settle_sec: float,
    verbose: bool | None = None,
) -> bool:
    """Capture inbound syslog TLS on the collector eth0; return True when pcap looks usable."""
    show = verbose_enabled(verbose)
    start_cmd = (
        f"pkill -x tcpdump 2>/dev/null || true; "
        f"rm -f {container_pcap}; "
        f"tcpdump -i eth0 -n -s 0 -w {container_pcap} {bpf_filter} -Z root "
        f"</dev/null >/dev/null 2>&1 & "
        f"echo started"
    )
    argv = ["docker", "exec", syslog_container, "sh", "-c", start_cmd]
    if show:
        echo_command("syslog wire KEX tcpdump (eth0)", argv)
    start = subprocess.run(argv, capture_output=True, text=True, check=False)
    if start.returncode != 0:
        return False

    try:
        time.sleep(0.5)
        bounce_logging()
        time.sleep(settle_sec)
    finally:
        subprocess.run(
            [
                "docker",
                "exec",
                syslog_container,
                "sh",
                "-c",
                "pkill -x tcpdump 2>/dev/null || true",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    size_check = subprocess.run(
        [
            "docker",
            "exec",
            syslog_container,
            "sh",
            "-c",
            f"test -s {container_pcap} && wc -c < {container_pcap}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if size_check.returncode != 0:
        return False
    try:
        return int(size_check.stdout.strip()) >= 50
    except ValueError:
        return False


def capture_eos_syslog_tls_key_share_group(
    *,
    switch_ip: str,
    bounce_logging: Callable[[], None],
    syslog_container: str,
    bridge: str | None = None,
    pcap_path: Path | None = None,
    settle_sec: float = 5.0,
    verbose: bool | None = None,
) -> int | None:
    """Capture cEOS→syslog ClientHello and return the client key_share group id.

    Returns None when capture or decode is unavailable. Capture runs via
    ``tcpdump -i eth0`` inside the syslog collector container (no host bridge
    access required).
    """
    _ = bridge, pcap_path
    container_pcap = "/tmp/quantum-safe-syslog-kex.pcap"
    bpf_filter = f"tcp port {SYSLOG_PORT} and host {switch_ip}"
    pcap_ok = _run_syslog_eth0_tcpdump_capture(
        syslog_container=syslog_container,
        container_pcap=container_pcap,
        bpf_filter=bpf_filter,
        bounce_logging=bounce_logging,
        settle_sec=settle_sec,
        verbose=verbose,
    )
    if not pcap_ok:
        return None

    hello_filter = tshark_client_hello_filter(switch_ip)
    decode = subprocess.run(
        [
            "docker",
            "exec",
            syslog_container,
            "sh",
            "-c",
            (
                "command -v tshark >/dev/null || apk add --no-cache tshark >/dev/null 2>&1; "
                f"tshark -r {container_pcap} "
                f"-Y '{hello_filter}' "
                "-T fields -e tls.handshake.extensions_key_share_group 2>/dev/null | tail -1"
            ),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    line = decode.stdout.strip()
    if line.isdigit():
        return int(line)
    return None


def wait_for_syslog_healthy(container: str, *, timeout_sec: int = 90) -> None:
    """Wait until Docker reports the syslog collector container as healthy."""
    deadline = time.time() + timeout_sec
    last_status = "unknown"
    while time.time() < deadline:
        result = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
                container,
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        last_status = result.stdout.strip() or "missing"
        if last_status == "healthy":
            return
        time.sleep(2)
    raise SyslogCheckError(
        f"{container} not healthy after {timeout_sec}s (last status: {last_status})"
    )


def tcpdump_captured_packet(output: str) -> bool:
    """Return True only when tcpdump stderr confirms a packet was captured."""
    return bool(re.search(r"\b1 packet captured\b", output))


def negotiated_pqc_group(output: str) -> bool:
    return PQC_GROUP in output


def tls_handshake_incomplete(output: str) -> bool:
    if negotiated_pqc_group(output):
        return False
    if "unexpected eof while reading" in output.lower():
        return True
    if "Negotiated TLS1.3 group: <NULL>" in output:
        return True
    if "no peer certificate available" in output and "Cipher is (NONE)" in output:
        return True
    return False


def cleartext_syslog_lines(logging_config: str) -> list[str]:
    """Return logging stanzas that would forward syslog without TLS."""
    violations: list[str] = []
    for raw in logging_config.splitlines():
        line = raw.strip()
        if not line.startswith("logging"):
            continue
        lower = line.lower()
        if "protocol udp" in lower:
            violations.append(line)
            continue
        if "protocol tcp" in lower and "protocol tls" not in lower:
            violations.append(line)
            continue
        if re.search(r"logging host \S+", line, flags=re.IGNORECASE) and "protocol tls" not in lower:
            violations.append(line)
    return violations


def expected_syslog_host_line(syslog_ip: str) -> str:
    return (
        f"logging vrf MGMT host {syslog_ip} {SYSLOG_PORT} "
        f"protocol tls ssl-profile {SYSLOG_SSL_PROFILE}"
    )


def cleartext_capture_filter(switch_ip: str) -> str:
    udp_ports = " or ".join(f"udp port {port}" for port in CLEARTEXT_SYSLOG_UDP_PORTS)
    tcp_ports = " or ".join(f"tcp port {port}" for port in CLEARTEXT_SYSLOG_TCP_PORTS)
    return f"src host {switch_ip} and (({udp_ports}) or ({tcp_ports}))"


def check_syslog_collector_listeners(netstat_udp: str, netstat_tcp: str) -> None:
    """Collector must listen on TLS 6514 only — no cleartext syslog UDP/TCP listeners."""
    for port in CLEARTEXT_SYSLOG_UDP_PORTS:
        if re.search(rf":{port}\s", netstat_udp):
            raise SyslogCheckError(f"syslog collector must not listen on UDP {port}")
    for port in CLEARTEXT_SYSLOG_TCP_PORTS:
        if re.search(rf":{port}\s", netstat_tcp):
            raise SyslogCheckError(f"syslog collector must not listen on TCP {port}")
    if f":{SYSLOG_PORT}" not in netstat_tcp:
        raise SyslogCheckError(f"syslog collector must listen on TCP {SYSLOG_PORT}")


def expected_syslog_host_lines(*syslog_ips: str) -> list[str]:
    return [expected_syslog_host_line(ip) for ip in syslog_ips]


def check_switch_syslog_logging_config(
    logging_config: str,
    *,
    node: str,
    syslog_ips: tuple[str, ...],
) -> None:
    """Verify remote syslog uses TLS only (no UDP/plain TCP hosts)."""
    violations = cleartext_syslog_lines(logging_config)
    if violations:
        raise SyslogCheckError(
            f"{node}: cleartext syslog forwarding configured: {violations!r}"
        )
    for expected in expected_syslog_host_lines(*syslog_ips):
        if expected not in logging_config:
            raise SyslogCheckError(f"{node}: expected syslog host line {expected!r}")


def _syslog_ssl_profile_valid(detail: Any) -> bool:
    """Return True when EOS reports the SYSLOG ssl profile as valid."""
    if isinstance(detail, (dict, list)):
        return json_truthy(detail, "profileState") or json_truthy(detail, "state")
    text = str(detail)
    if "State: valid" in text:
        return True
    return bool(
        re.search(r"""['"]profileState['"]\s*:\s*['"]valid['"]""", text)
        or re.search(r"""['"]state['"]\s*:\s*['"]valid['"]""", text)
    )


def check_switch_syslog_ssl_profile_detail(detail: str | Any, *, node: str) -> None:
    if not _syslog_ssl_profile_valid(detail):
        raise SyslogCheckError(f"{node} SYSLOG ssl profile must be valid")
    if isinstance(detail, (dict, list)):
        if not json_tree_contains(detail, PQC_GROUP):
            raise SyslogCheckError(f"{node} SYSLOG ssl profile must advertise {PQC_GROUP!r}")
        return
    text = str(detail)
    if PQC_GROUP not in text:
        raise SyslogCheckError(f"{node} SYSLOG ssl profile must advertise {PQC_GROUP!r}")


def probe_syslog_tls_pqc(
    *,
    syslog_ip: str,
    clab_name: str = LAB_NAME,
    syslog_container: str | None = None,
    verbose: bool | None = None,
) -> str:
    """TLS 1.3 PQC handshake to the syslog collector from the probe client."""
    output = run_openssl_s_client(
        connect=hostport(syslog_ip, SYSLOG_PORT),
        ca_file=probe_syslog_ca_path(),
        groups=PQC_GROUP,
        servername="syslog",
        clab_name=clab_name,
        verbose=verbose,
    )
    if "CONNECTED" not in output and "CONNECTION ESTABLISHED" not in output:
        raise SyslogCheckError(f"syslog TLS handshake failed:\n{output[-800:]}")
    if tls_handshake_incomplete(output):
        health_hint = ""
        if syslog_container:
            health_hint = (
                f"collector may still be starting — retry or check "
                f"'docker inspect --format={{.State.Health.Status}} {syslog_container}'"
            )
        raise SyslogCheckError(
            "syslog TLS handshake incomplete (TCP connected but no TLS response); "
            f"{health_hint}".rstrip()
        )
    if not negotiated_pqc_group(output):
        raise SyslogCheckError(f"syslog TLS: expected PQC group {PQC_GROUP!r}")
    return output


def probe_syslog_delivery_no_cleartext(
    docker_exec: Callable[..., subprocess.CompletedProcess[str]],
    send_log: Callable[[], None],
    *,
    syslog_container: str,
    switch_ip: str,
    node: str,
    needle: str | None = None,
    marker_id: str | None = None,
    delivery_timeout_sec: int = 45,
) -> None:
    """Send a probe log while watching for cleartext syslog packets from the switch."""
    _ = marker_id  # retained for callers; capture no longer uses marker files
    probe_needle = needle or f"{PROBE_MESSAGE}-{node}"
    capture_filter = cleartext_capture_filter(switch_ip)
    cleartext_seen = threading.Event()

    def watch_cleartext() -> None:
        cmd = (
            f"timeout 30 tcpdump -i eth0 -n -c 1 -Z root "
            f"{shlex.quote(capture_filter)}"
        )
        result = docker_exec(syslog_container, cmd, check=False)
        if tcpdump_captured_packet(result.stdout + result.stderr):
            cleartext_seen.set()

    docker_exec(syslog_container, "pkill -x tcpdump 2>/dev/null || true", check=False)
    watcher = threading.Thread(target=watch_cleartext, daemon=True)
    watcher.start()
    time.sleep(0.5)
    send_log()

    deadline = time.time() + delivery_timeout_sec
    while time.time() < deadline:
        if cleartext_seen.is_set():
            docker_exec(syslog_container, "pkill -x tcpdump 2>/dev/null || true", check=False)
            raise SyslogCheckError(
                f"{node}: cleartext syslog observed from {switch_ip} "
                f"(classic UDP/TCP syslog ports)"
            )
        grep = docker_exec(
            syslog_container,
            f"grep -F '{probe_needle}' {SYSLOG_LOG_PATH} || true",
            check=False,
        )
        if probe_needle in grep.stdout:
            docker_exec(syslog_container, "pkill -x tcpdump 2>/dev/null || true", check=False)
            return
        time.sleep(2)
    docker_exec(syslog_container, "pkill -x tcpdump 2>/dev/null || true", check=False)
    raise SyslogCheckError(f"{node}: timed out waiting for TLS syslog delivery of {probe_needle!r}")
