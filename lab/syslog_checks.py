"""Shared syslog-over-TLS PQC checks for live lab verification."""

from __future__ import annotations

import re
import subprocess
import threading
import time
from typing import Any, Callable

from lab.ceos_json import json_tree_contains, json_truthy
from lab.topology_contract import SYSLOG_PORT, SYSLOG_SSL_PROFILE, hostport

PQC_GROUP = "X25519MLKEM768"
OPENSSL_PQC_CNF = "/etc/syslog-ng/openssl-pqc.cnf"
SYSLOG_LOG_PATH = "/var/log/syslog/eos.log"
PROBE_MESSAGE = "quantum-safe-syslog-probe"
CEOS_SYSLOG_NODES = ("ceos1-both", "ceos2-pqc", "ceos3-qkd")

CLEARTEXT_SYSLOG_UDP_PORTS = (514, 601)
CLEARTEXT_SYSLOG_TCP_PORTS = (514,)


class SyslogCheckError(RuntimeError):
    """Raised when a syslog PQC or encryption check fails."""


def tcpdump_captured_packet(output: str) -> bool:
    """Return True only when tcpdump stderr confirms a packet was captured."""
    return bool(re.search(r"\b1 packet captured\b", output))


def negotiated_pqc_group(output: str) -> bool:
    return PQC_GROUP in output


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
    docker_exec: Callable[..., subprocess.CompletedProcess[str]],
    *,
    syslog_container: str,
    syslog_ip: str,
) -> str:
    command = (
        f"OPENSSL_CONF={OPENSSL_PQC_CNF} "
        f"openssl s_client -connect {hostport(syslog_ip, SYSLOG_PORT)} -servername syslog -tls1_3 "
        f"-groups {PQC_GROUP} </dev/null 2>&1"
    )
    result = docker_exec(syslog_container, command, check=False)
    output = result.stdout + result.stderr
    if "CONNECTED" not in output and "CONNECTION ESTABLISHED" not in output:
        raise SyslogCheckError(f"syslog TLS handshake failed:\n{output[-800:]}")
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
        result = subprocess.run(
            [
                "docker",
                "exec",
                syslog_container,
                "timeout",
                "30",
                "tcpdump",
                "-i",
                "eth0",
                "-n",
                "-c",
                "1",
                "-Z",
                "root",
                capture_filter,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
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
