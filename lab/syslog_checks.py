"""Shared syslog-over-TLS PQC checks for live lab verification."""

from __future__ import annotations

import re
import subprocess
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


def check_switch_syslog_logging_config(
    logging_config: str,
    *,
    node: str,
    syslog_ip: str,
) -> None:
    """Verify remote syslog uses TLS only (no UDP/plain TCP hosts)."""
    violations = cleartext_syslog_lines(logging_config)
    if violations:
        raise SyslogCheckError(
            f"{node}: cleartext syslog forwarding configured: {violations!r}"
        )
    expected = expected_syslog_host_line(syslog_ip)
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
    delivery_timeout_sec: int = 45,
) -> None:
    """Send a probe log while watching for cleartext syslog packets from the switch."""
    needle = f"{PROBE_MESSAGE}-{node}"
    capture_filter = cleartext_capture_filter(switch_ip)
    marker = f"/tmp/cleartext-syslog-{node}.chk"

    docker_exec(syslog_container, "pkill -x tcpdump 2>/dev/null || true", check=False)
    docker_exec(syslog_container, f"rm -f {marker}", check=False)
    docker_exec(
        syslog_container,
        f"(timeout 30 tcpdump -i eth0 -n -c 1 -Z root '{capture_filter}' 2>/dev/null "
        f"&& echo CAPTURED > {marker}) &",
        check=False,
    )
    time.sleep(1)
    send_log()

    deadline = time.time() + delivery_timeout_sec
    while time.time() < deadline:
        captured = docker_exec(
            syslog_container,
            f"test -f {marker} && echo yes || echo no",
            check=False,
        )
        if "yes" in captured.stdout:
            raise SyslogCheckError(
                f"{node}: cleartext syslog observed from {switch_ip} "
                f"(classic UDP/TCP syslog ports)"
            )
        grep = docker_exec(
            syslog_container,
            f"grep -F '{needle}' {SYSLOG_LOG_PATH} || true",
            check=False,
        )
        if needle in grep.stdout:
            return
        time.sleep(2)
    raise SyslogCheckError(f"{node}: timed out waiting for TLS syslog delivery of {needle!r}")
