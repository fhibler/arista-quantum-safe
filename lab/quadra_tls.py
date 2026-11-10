"""Measure the real QuaDRA clients' TLS KEX during a normal key rotation."""

from __future__ import annotations

import csv
import io
import ipaddress
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from lab.topology_contract import TLS_PQC_GROUP, container_name
from lab.verbose import echo_command, verbose_enabled
from lab.report import report_wait

PQC_GROUP_ID = 0x11EC
CAPTURE_TIMEOUT_GRACE_SEC = 15
DECODE_TIMEOUT_SEC = 30
LOG_TIMEOUT_SEC = 20
HELLO_RETRY_RANDOM = "cf21ad74e59a6111be1d8c021e65b891c2a211167abb8c5e079e09e2c8a8339c"
FIELDS = (
    "frame.number", "frame.time_epoch", "ip.src", "ipv6.src", "ip.dst", "ipv6.dst",
    "tcp.srcport", "tcp.dstport", "tcp.stream", "tls.handshake.type",
    "tls.handshake.random", "tls.handshake.extensions.supported_version",
    "tls.handshake.extensions_key_share_group", "tls.handshake.extensions_supported_group",
    "tls.handshake.ciphersuite",
)


class QuadraTlsError(RuntimeError):
    """Measurement unavailable, or QuaDRA negotiated a non-hybrid connection."""


@dataclass(frozen=True)
class QuadraTlsPeer:
    node: str
    kme_node: str
    server_ip: str
    port: int
    endpoint: str


@dataclass(frozen=True)
class QuadraTlsHandshake:
    stream: str
    client_ip: str
    client_port: int
    server_frame: int
    time_epoch: str
    tls13: bool
    group: int | None
    cipher: int
    offered_groups: tuple[int, ...]

    @property
    def pqc_confirmed(self) -> bool:
        return self.tls13 and self.group == PQC_GROUP_ID


def quadra_tls_peer(node: str, kme_endpoint: str) -> QuadraTlsPeer:
    """Use the agent's operational KME endpoint, including IPv6 when configured."""
    try:
        parsed = urlsplit(f"//{kme_endpoint}")
        server_ip = str(ipaddress.ip_address(parsed.hostname or ""))
        port = parsed.port
        if port is None or parsed.path or parsed.query or parsed.fragment or parsed.username:
            raise ValueError("expected IP:port")
    except ValueError as exc:
        raise QuadraTlsError(f"{node}: invalid QuaDRA KME endpoint {kme_endpoint!r}") from exc
    return QuadraTlsPeer(
        node, "kme-a" if node == "ceos1-both" else "kme-b", server_ip, port,
        "enc_keys" if node == "ceos1-both" else "dec_keys",
    )


def _numbers(value: str) -> tuple[int, ...]:
    return tuple(int(part, 0) for part in value.split(",") if part)


def parse_quadra_tls_handshakes(output: str, peer: QuadraTlsPeer) -> list[QuadraTlsHandshake]:
    """Pair ClientHello and final ServerHello by TCP stream; ignore HelloRetryRequest.

    Client offers alone never establish PQC. Every observed final ServerHello is
    retained so a later hybrid handshake cannot hide an earlier classical one.
    """
    clients: dict[str, dict[str, str]] = {}
    handshakes: dict[str, QuadraTlsHandshake] = {}
    for row in csv.DictReader(io.StringIO(output), delimiter="\t"):
        src = row["ip.src"] or row["ipv6.src"]
        dst = row["ip.dst"] or row["ipv6.dst"]
        stream = row["tcp.stream"]
        kinds = _numbers(row["tls.handshake.type"])
        if 1 in kinds and dst == peer.server_ip and int(row["tcp.dstport"]) == peer.port:
            clients[stream] = row
        if 2 not in kinds or src != peer.server_ip or int(row["tcp.srcport"]) != peer.port:
            continue
        if row["tls.handshake.random"].replace(":", "").lower() == HELLO_RETRY_RANDOM:
            continue
        client = clients.get(stream)
        if client is None:
            continue  # Capture began mid-handshake; there is no complete sample.
        client_ip = client["ip.src"] or client["ipv6.src"]
        if dst != client_ip or row["tcp.dstport"] != client["tcp.srcport"]:
            continue
        groups = _numbers(row["tls.handshake.extensions_key_share_group"])
        ciphers = _numbers(row["tls.handshake.ciphersuite"])
        if len(groups) > 1 or len(ciphers) != 1:
            raise QuadraTlsError(f"{peer.node}: ambiguous ServerHello in stream {stream}")
        handshakes.setdefault(stream, QuadraTlsHandshake(
            stream=stream,
            client_ip=client_ip,
            client_port=int(client["tcp.srcport"]),
            server_frame=int(row["frame.number"]),
            time_epoch=row["frame.time_epoch"],
            tls13=_numbers(row["tls.handshake.extensions.supported_version"]) == (0x0304,),
            group=groups[0] if groups else None,
            cipher=ciphers[0],
            offered_groups=_numbers(client["tls.handshake.extensions_supported_group"]),
        ))
    return list(handshakes.values())


def capture_quadra_tls(
    peer: QuadraTlsPeer, *, clab_name: str, duration: int, output_dir: Path,
    verbose: bool | None = None,
) -> Path:
    """Passively capture the agent's MGMT namespace; remote timeout stops tcpdump."""
    pcap = output_dir / f"{peer.node}.pcap"
    argv = [
        "docker", "exec", container_name(peer.node, lab_name=clab_name),
        "ip", "netns", "exec", "ns-MGMT", "timeout", "-s", "INT", str(duration),
        "tcpdump", "-i", "any", "-p", "-nn", "-s", "0", "-U", "-w", "-",
        f"tcp port {peer.port} and host {peer.server_ip}",
    ]
    if verbose_enabled(verbose):
        echo_command(f"{peer.node} passive QuaDRA TLS capture", argv)
    with pcap.open("wb") as capture, (output_dir / f"{peer.node}.tcpdump.log").open("w") as log:
        try:
            result = subprocess.run(
                argv, stdout=capture, stderr=log, check=False, timeout=duration + CAPTURE_TIMEOUT_GRACE_SEC,
            )
        except subprocess.TimeoutExpired as exc:
            raise QuadraTlsError(f"{peer.node}: capture timed out; TLS KEX unverified") from exc
    if result.returncode not in (0, 124) or pcap.stat().st_size <= 24:
        raise QuadraTlsError(
            f"{peer.node}: no usable capture; TLS KEX unverified (see {pcap.with_suffix('.tcpdump.log')})"
        )
    return pcap


def decode_quadra_tls(pcap: Path, peer: QuadraTlsPeer, *, clab_name: str) -> list[QuadraTlsHandshake]:
    """Use the deployed test-runner's tshark; no host tools or image changes needed."""
    argv = [
        "docker", "exec", "-i", container_name("test-runner", lab_name=clab_name),
        "tshark", "-n", "-r", "-", "-d", f"tcp.port=={peer.port},tls",
        "-Y", "tls.handshake.type == 1 || tls.handshake.type == 2",
        "-T", "fields", "-E", "header=y",
    ]
    for field in FIELDS:
        argv.extend(["-e", field])
    with pcap.open("rb") as capture:
        result = subprocess.run(argv, stdin=capture, capture_output=True, text=True, timeout=DECODE_TIMEOUT_SEC, check=False)
    pcap.with_suffix(".tls.tsv").write_text(result.stdout)
    if result.returncode:
        raise QuadraTlsError(f"{peer.node}: TLS decode failed; KEX unverified: {result.stderr.strip()}")
    try:
        return parse_quadra_tls_handshakes(result.stdout, peer)
    except (KeyError, ValueError) as exc:
        raise QuadraTlsError(f"{peer.node}: invalid tshark output; TLS KEX unverified") from exc


def successful_key_requests(logs: str, peer: QuadraTlsPeer, client_ips: set[str]) -> list[str]:
    """Select fresh, successful key requests from captured clients, not lab curl probes."""
    matches = []
    for line in logs.splitlines():
        source = re.search(r"(?:^|\s)(\S+) - - \[", line)
        if source is None:
            continue
        ip = source.group(1).removeprefix("::ffff:")
        if ip in client_ips and re.search(rf'"POST /api/v1/keys/[^ /]+/{peer.endpoint} HTTP/\S+" 200\b', line):
            matches.append(line)
    return matches


def verify_quadra_tls(
    peers: list[QuadraTlsPeer], *, clab_name: str, duration: int = 135,
    output_dir: Path = Path("lab/.gen/quadra-tls"), verbose: bool | None = None,
) -> None:
    """Require hybrid TLS for both real QuaDRA clients, preserving evidence on failure."""
    from lab.report import report_ok

    output_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    report_wait(
        "QuaDRA TLS capture and analysis", expected_sec=duration,
        maximum_sec=duration + CAPTURE_TIMEOUT_GRACE_SEC + len(peers) * (DECODE_TIMEOUT_SEC + LOG_TIMEOUT_SEC),
        detail=f"{duration}s capture for both peers concurrently; includes capture grace and decode/log timeouts; "
               f"functional checks extra; evidence: {output_dir}",
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        captures = list(pool.map(lambda peer: capture_quadra_tls(
            peer, clab_name=clab_name, duration=duration, output_dir=output_dir, verbose=verbose,
        ), peers))
    ended = datetime.now(timezone.utc).isoformat()
    evidence: dict = {"started_utc": started, "ended_utc": ended, "peers": []}
    failures = []
    for peer, pcap in zip(peers, captures):
        handshakes = decode_quadra_tls(pcap, peer, clab_name=clab_name)
        result = subprocess.run(
            ["docker", "logs", "--since", started, "--until", ended,
             container_name(peer.kme_node, lab_name=clab_name)],
            capture_output=True, text=True, check=False, timeout=LOG_TIMEOUT_SEC,
        )
        requests = successful_key_requests(result.stdout + result.stderr, peer, {h.client_ip for h in handshakes})
        (output_dir / f"{peer.node}.requests.log").write_text("\n".join(requests) + "\n")
        evidence["peers"].append({
            **asdict(peer), "handshakes": [asdict(h) for h in handshakes],
            "successful_key_requests": len(requests),
        })
        if not handshakes or not requests or result.returncode:
            failures.append(f"{peer.node}: no complete handshake / successful key-delivery sample; TLS KEX unverified")
        elif not all(h.pqc_confirmed for h in handshakes):
            groups = ", ".join(str(h.group) for h in handshakes)
            failures.append(f"{peer.node}: not PQC-safe; observed TLS key_share groups {groups}")
        else:
            report_ok("[wire] ", f"{peer.node} → {peer.kme_node}: TLS 1.3, KEX {TLS_PQC_GROUP}; "
                      f"{len(handshakes)} handshake(s), {len(requests)} successful /{peer.endpoint} request(s)")
    (output_dir / "result.json").write_text(json.dumps(evidence, indent=2) + "\n")
    if failures:
        raise QuadraTlsError("; ".join(failures) + f" (evidence: {output_dir})")
