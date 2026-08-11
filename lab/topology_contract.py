"""Topology and configuration contract validation for the Quantum Safe lab."""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
LAB_NAME = "quantum-safe"
CLAB_PREFIX = "arista"
LAB_DISPLAY_NAME = "Quantum Safe"
MGMT_NETWORK = "quantum-safe-mgmt"
MGMT_BRIDGE = "mgmt-bridge"
MGMT_NODES = frozenset({"ceos1-both", "ceos2-pqc", "ceos3-qkd", "radius", "syslog", "kme-a", "kme-b"})
RADIUS_IMAGE = "quantum-safe-radius:latest"
SYSLOG_IMAGE = "quantum-safe-syslog:latest"
TOPOLOGY_PATH = REPO_ROOT / "lab" / f"{LAB_NAME}.clab.yml"
TOPOLOGY_ANNOTATIONS_PATH = REPO_ROOT / "lab" / f"{LAB_NAME}.clab.yml.annotations.json"
GEN_TOPOLOGY_PATH = REPO_ROOT / "lab" / f".gen.{LAB_NAME}.clab.yml"
GEN_TOPOLOGY_ANNOTATIONS_PATH = REPO_ROOT / "lab" / f".gen.{LAB_NAME}.clab.yml.annotations.json"
GEN_CONFIG_DIR = REPO_ROOT / "lab" / ".gen"


def container_name(node: str, *, lab_name: str | None = None, prefix: str | None = None) -> str:
    """Return the Containerlab Docker container name for a lab node."""
    return f"{prefix or CLAB_PREFIX}-{lab_name or LAB_NAME}-{node}"

DEFAULT_MGMT_SUBNET = "172.20.127.0/24"
DEFAULT_MGMT_IPV6_SUBNET = "2001:db8:127::/64"
DOC_PREFIX = "2001:db8"
MGMT_HOST_SUFFIXES = {
    "ceos1-both": 11,
    "ceos2-pqc": 12,
    "ceos3-qkd": 13,
    "host1": 21,
    "host2": 22,
    "host3": 23,
    "radius": 50,
    "syslog": 53,
    "kme-a": 51,
    "kme-b": 52,
}


def mgmt_gateway(subnet: str | None = None) -> str:
    """Return the Containerlab bridge gateway (.1) for a mgmt subnet."""
    network = ipaddress.ip_network(subnet or DEFAULT_MGMT_SUBNET, strict=False)
    return str(network.network_address + 1)


def mgmt_ip(subnet: str | None, host_suffix: int) -> str:
    """Return a mgmt host address within subnet using a fixed host octet."""
    network = ipaddress.ip_network(subnet or DEFAULT_MGMT_SUBNET, strict=False)
    return str(network.network_address + host_suffix)


def mgmt_prefix_len(subnet: str | None = None) -> int:
    """Return the prefix length for mgmt interface addresses."""
    return ipaddress.ip_network(subnet or DEFAULT_MGMT_SUBNET, strict=False).prefixlen


def mgmt_ips_for_subnet(subnet: str | None = None) -> dict[str, str]:
    """Return locked mgmt IPs for all lab nodes on the given subnet."""
    return {
        host: mgmt_ip(subnet, suffix) for host, suffix in MGMT_HOST_SUFFIXES.items()
    }


def mgmt_ipv6_gateway(subnet: str | None = None) -> str:
    """Return the Containerlab bridge IPv6 gateway (::1) for a mgmt subnet."""
    network = ipaddress.ip_network(subnet or DEFAULT_MGMT_IPV6_SUBNET, strict=False)
    return str(network.network_address + 1)


def mgmt_ipv6_ip(subnet: str | None, host_suffix: int) -> str:
    """Return a mgmt IPv6 host address using the same decimal suffix as IPv4 mgmt."""
    network = ipaddress.ip_network(subnet or DEFAULT_MGMT_IPV6_SUBNET, strict=False)
    return f"{network.network_address}{host_suffix}"


def mgmt_ipv6_prefix_len(subnet: str | None = None) -> int:
    """Return the prefix length for mgmt IPv6 interface addresses."""
    return ipaddress.ip_network(subnet or DEFAULT_MGMT_IPV6_SUBNET, strict=False).prefixlen


def mgmt_ipv6_ips_for_subnet(subnet: str | None = None) -> dict[str, str]:
    """Return locked mgmt IPv6 addresses for all lab nodes on the given subnet."""
    return {
        host: mgmt_ipv6_ip(subnet, suffix) for host, suffix in MGMT_HOST_SUFFIXES.items()
    }


MGMT_SUBNET = DEFAULT_MGMT_SUBNET
MGMT_IPS = mgmt_ips_for_subnet(DEFAULT_MGMT_SUBNET)
MGMT_IPV6_SUBNET = DEFAULT_MGMT_IPV6_SUBNET
MGMT_IPV6_IPS = mgmt_ipv6_ips_for_subnet(DEFAULT_MGMT_IPV6_SUBNET)

IP_FAMILY_IPV4 = "ipv4"
IP_FAMILY_IPV6 = "ipv6"
IP_FAMILIES = (IP_FAMILY_IPV4, IP_FAMILY_IPV6)
FAMILY_LABELS = {IP_FAMILY_IPV4: "IPv4", IP_FAMILY_IPV6: "IPv6"}


def family_label(family: str) -> str:
    """Return a display label for an address family slug."""
    return FAMILY_LABELS[family]


def is_ipv6_address(addr: str) -> bool:
    """Return True when addr looks like IPv6 (contains a colon)."""
    return ":" in addr


def bracketed_host(addr: str) -> str:
    """Return addr wrapped in [] when IPv6 (for URLs and OpenSSL connect strings)."""
    return f"[{addr}]" if is_ipv6_address(addr) else addr


def hostport(addr: str, port: int) -> str:
    """Return host:port with IPv6 bracket notation when needed."""
    return f"{bracketed_host(addr)}:{port}"


def mgmt_ips_for_family(
    family: str,
    *,
    mgmt_subnet: str | None = None,
    mgmt_ipv6_subnet: str | None = None,
) -> dict[str, str]:
    """Return locked mgmt addresses for all lab nodes in the given address family."""
    if family == IP_FAMILY_IPV6:
        return mgmt_ipv6_ips_for_subnet(mgmt_ipv6_subnet)
    if family == IP_FAMILY_IPV4:
        return mgmt_ips_for_subnet(mgmt_subnet)
    raise ValueError(f"unsupported address family: {family!r}")


def mgmt_node_ip(
    node: str,
    family: str,
    *,
    mgmt_subnet: str | None = None,
    mgmt_ipv6_subnet: str | None = None,
) -> str:
    """Return a single node's mgmt address for the given address family."""
    return mgmt_ips_for_family(
        family,
        mgmt_subnet=mgmt_subnet,
        mgmt_ipv6_subnet=mgmt_ipv6_subnet,
    )[node]

LINKS = [
    ("ceos1-both:eth1", "ceos2-pqc:eth1"),
    ("ceos1-both:eth3", "ceos3-qkd:eth1"),
    ("ceos1-both:eth8", "host1:eth1"),
    ("ceos2-pqc:eth8", "host2:eth1"),
    ("ceos3-qkd:eth8", "host3:eth1"),
]

CEOS_MGMT_NODES = frozenset({"ceos1-both", "ceos2-pqc", "ceos3-qkd"})
MGMT_LINUX_NODES = frozenset({"radius", "syslog", "kme-a", "kme-b"})
CEOS_MACSEC_NODES = frozenset({"ceos1-both", "ceos2-pqc"})
CEOS_QUADRA_NODES = frozenset({"ceos1-both", "ceos3-qkd"})

# QuaDRA static SAK MACsec on ceos1-both:eth3 ↔ ceos3-qkd:eth1 (10.255.0.5/30 ↔ 10.255.0.6/30).
QUADRA_SWIX = "QuaDRA-1.0.9.rel4.swix"
QUADRA_SWIX_HOST = REPO_ROOT / "experimental" / "quadra" / QUADRA_SWIX
QUADRA_MACSEC_PROFILE_MASTER = "quadra-master"
QUADRA_MACSEC_PROFILE_SLAVE = "quadra-slave"
QUADRA_MACSEC_INTF = {
    "ceos1-both": "Ethernet3",
    "ceos3-qkd": "Ethernet1",
}
QUADRA_PEER_IP = {
    "ceos1-both": "10.255.0.6",
    "ceos3-qkd": "10.255.0.5",
}
QUADRA_SC_RX_ID = "01:02:03:0a:0b:0c::1001"
QUADRA_SC_TX_ID = "01:02:03:0a:0b:0c::1002"
# 256-bit placeholder SAKs (64 hex chars); replaced on first QuaDRA rotation.
QUADRA_KEY_RX = "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"
QUADRA_KEY_TX = "202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f"
QUADRA_PEER_PORT = 50100
QUADRA_KME_BUNDLE = {
    "ceos1-both": "kme-sae-bundle.pem",
    "ceos3-qkd": "kme-sae-b-bundle.pem",
}

DEFAULT_CEOS_IMAGE = "ceos:4.36.1F"
CEOS_IMAGE_PLACEHOLDER = "${CEOS_IMAGE}"
MGMT_SUBNET_PLACEHOLDER = "${MGMT_SUBNET}"
MGMT_IPV6_SUBNET_PLACEHOLDER = "${MGMT_IPV6_SUBNET}"
MGMT_VRF_ENV = "MGMT"
MGMT_VRF_ENV = "MGMT"
RADSEC_SECRET = "radsec"
RADSEC_PORT = 2083
SSL_PROFILE = "RADSEC"
SYSLOG_SSL_PROFILE = "SYSLOG"
SYSLOG_PORT = 6514
EAPI_SSL_PROFILE = "EAPI"
GNMI_SSL_PROFILE = "GNMI"
GNMI_PORT = 6030
RESTCONF_SSL_PROFILE = "RESTCONF"
RESTCONF_PORT = 6020
EOSSDKRPC_SSL_PROFILE = GNMI_SSL_PROFILE
EOSSDKRPC_PORT = 9543
CONTROL_PLANE_ACL = "quantum-safe-cp"
PROBE_CLIENT_CERT = "/etc/raddb/certs/probe/{node}-client.pem"
PROBE_CLIENT_KEY = "/etc/raddb/certs/probe/{node}-client.key"
MACSEC_PROFILE = "dynamic"
DOT1X_SUPPLICANT_PROFILE = "macsec-sp"
DOT1X_EAP_SSL_PROFILE = "DOT1X"
DOT1X_EAP_IDENTITY = "ceos2-pqc"
DOT1X_REAUTH_PERIOD_SEC = 60
TLS_PQC_GROUP = "X25519MLKEM768"
TLS_PQC_EOS_GROUPS = TLS_PQC_GROUP
# Syslog-over-TLS: hybrid first, classical fallback (cEOS 4.36.1F syslog client gap on PQC-only).
SYSLOG_TLS_PQC_SAFE_EOS_GROUPS = "X25519MLKEM768:ecdh_x25519:secp256r1"
SYSLOG_TLS_PQC_SAFE_OPENSSL_GROUPS = "X25519MLKEM768:secp256r1:X25519:ffdhe2048"
SSH_PQC_KEX = "mlkem768x25519-sha256"
SSH_PQC_CIPHERS = (
    "aes256-gcm@openssh.com aes128-gcm@openssh.com chacha20-poly1305@openssh.com"
)
SSH_PQC_MACS = "hmac-sha2-256 hmac-sha2-512"
RADIUS_SERVER_IPV4 = MGMT_IPS["radius"]
SYSLOG_SERVER_IPV4 = MGMT_IPS["syslog"]
RADIUS_SERVER_IPV6 = MGMT_IPV6_IPS["radius"]
SYSLOG_SERVER_IPV6 = MGMT_IPV6_IPS["syslog"]
# RadSec uses IPv6; syslog-over-TLS is dual-stack (IPv4 + IPv6 TLS logging hosts).
RADIUS_SERVER_IP = RADIUS_SERVER_IPV6
KME_A_SERVER_IP = MGMT_IPS["kme-a"]
KME_B_SERVER_IP = MGMT_IPS["kme-b"]

KME_IMAGE = "quantum-safe-kme:latest"
KME_A_PORT = 8010
KME_B_PORT = 8020
KME_A_ID = "9b7703f1-9b6d-403d-b850-18a1b6fd6d8f"
KME_B_ID = "ffb23f4d-5d5b-47e5-a8c5-fe9e47d646cd"
KME_SAE_ID = "25840139-0dd4-49ae-ba1e-b86731601803"
KME_B_SAE_ID = "c565d5aa-8670-4446-8471-b0e53e315d2a"
KME_KEY_SIZE = 32  # AES-256 key length in bytes (ETSI API uses bits: 256)
KME_KEY_SIZE_BITS = KME_KEY_SIZE * 8

# Lab nodes allowed to call the KME SAE API (iptables allowlist on kme-a / kme-b).
KME_SAE_CLIENT_NODES = ("kme-a", "ceos1-both", "ceos3-qkd")

# KME SAE client material bind-mounted on cEOS switches (curl from MGMT VRF).
CEOS_KME_BINDS = [
    "../lab/.gen/kme-pki/ca.crt.pem:/mnt/flash/kme-ca.crt.pem:ro",
    "../lab/.gen/kme-pki/sae.crt.pem:/mnt/flash/kme-sae.crt.pem:ro",
    "../lab/.gen/kme-pki/sae.key.pem:/mnt/flash/kme-sae.key.pem:ro",
    "../lab/.gen/kme-pki/sae-b.crt.pem:/mnt/flash/kme-sae-b.crt.pem:ro",
    "../lab/.gen/kme-pki/sae-b.key.pem:/mnt/flash/kme-sae-b.key.pem:ro",
    "../lab/.gen/kme-pki/kme-sae-bundle.pem:/mnt/flash/kme-sae-bundle.pem:ro",
    "../lab/.gen/kme-pki/kme-sae-b-bundle.pem:/mnt/flash/kme-sae-b-bundle.pem:ro",
]
CEOS_KME_NODES = frozenset({"ceos1-both", "ceos3-qkd"})

# Backward-compatible aliases for callers that still use the old names.
KME_SERVER_IP = KME_A_SERVER_IP
KME2_SERVER_IP = KME_B_SERVER_IP
KME_PORT = KME_A_PORT
KME2_PORT = KME_B_PORT
KME_ID = KME_A_ID
KME2_ID = KME_B_ID
KME2_SAE_ID = KME_B_SAE_ID

HOST_DATA_PLANE = {
    "host1": {
        "addr": "10.0.1.1/24",
        "gateway": "10.0.1.254",
        "addr6": f"{DOC_PREFIX}:1::1/64",
        "gateway6": f"{DOC_PREFIX}:1::fe",
    },
    "host2": {
        "addr": "10.0.2.1/24",
        "gateway": "10.0.2.254",
        "addr6": f"{DOC_PREFIX}:2::1/64",
        "gateway6": f"{DOC_PREFIX}:2::fe",
    },
    "host3": {
        "addr": "10.0.3.1/24",
        "gateway": "10.0.3.254",
        "addr6": f"{DOC_PREFIX}:3::1/64",
        "gateway6": f"{DOC_PREFIX}:3::fe",
    },
}

def ceos_data_plane(
    subnet: str | None = None,
    *,
    mgmt_ipv6_subnet: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Return locked cEOS data-plane expectations for the given mgmt subnet."""
    ips = mgmt_ips_for_subnet(subnet)
    ips6 = mgmt_ipv6_ips_for_subnet(mgmt_ipv6_subnet)
    prefix = mgmt_prefix_len(subnet)
    prefix6 = mgmt_ipv6_prefix_len(mgmt_ipv6_subnet)
    return {
        "ceos1-both": {
            "mgmt_ip": f"{ips['ceos1-both']}/{prefix}",
            "mgmt_gateway": mgmt_gateway(subnet),
            "mgmt_ip6": f"{ips6['ceos1-both']}/{prefix6}",
            "mgmt_gateway6": mgmt_ipv6_gateway(mgmt_ipv6_subnet),
            "eth1": "10.255.0.1/30",
            "eth1_ipv6": f"{DOC_PREFIX}:255:0::1/126",
            "eth3": "10.255.0.5/30",
            "eth3_ipv6": f"{DOC_PREFIX}:255:0::5/126",
            "eth8": "10.0.1.254/24",
            "eth8_ipv6": f"{DOC_PREFIX}:1::fe/64",
            "static_routes": [
                ("10.0.2.0/24", "10.255.0.2"),
                ("10.0.3.0/24", "10.255.0.6"),
            ],
            "static_routes6": [
                (f"{DOC_PREFIX}:2::/64", f"{DOC_PREFIX}:255:0::2"),
                (f"{DOC_PREFIX}:3::/64", f"{DOC_PREFIX}:255:0::6"),
            ],
        },
        "ceos2-pqc": {
            "mgmt_ip": f"{ips['ceos2-pqc']}/{prefix}",
            "mgmt_gateway": mgmt_gateway(subnet),
            "mgmt_ip6": f"{ips6['ceos2-pqc']}/{prefix6}",
            "mgmt_gateway6": mgmt_ipv6_gateway(mgmt_ipv6_subnet),
            "eth1": "10.255.0.2/30",
            "eth1_ipv6": f"{DOC_PREFIX}:255:0::2/126",
            "eth8": "10.0.2.254/24",
            "eth8_ipv6": f"{DOC_PREFIX}:2::fe/64",
            "static_routes": [
                ("10.0.1.0/24", "10.255.0.1"),
                ("10.0.3.0/24", "10.255.0.1"),
            ],
            "static_routes6": [
                (f"{DOC_PREFIX}:1::/64", f"{DOC_PREFIX}:255:0::1"),
                (f"{DOC_PREFIX}:3::/64", f"{DOC_PREFIX}:255:0::1"),
            ],
        },
        "ceos3-qkd": {
            "mgmt_ip": f"{ips['ceos3-qkd']}/{prefix}",
            "mgmt_gateway": mgmt_gateway(subnet),
            "mgmt_ip6": f"{ips6['ceos3-qkd']}/{prefix6}",
            "mgmt_gateway6": mgmt_ipv6_gateway(mgmt_ipv6_subnet),
            "eth1": "10.255.0.6/30",
            "eth1_ipv6": f"{DOC_PREFIX}:255:0::6/126",
            "eth8": "10.0.3.254/24",
            "eth8_ipv6": f"{DOC_PREFIX}:3::fe/64",
            "static_routes": [
                ("10.0.1.0/24", "10.255.0.5"),
                ("10.0.2.0/24", "10.255.0.5"),
            ],
            "static_routes6": [
                (f"{DOC_PREFIX}:1::/64", f"{DOC_PREFIX}:255:0::5"),
                (f"{DOC_PREFIX}:2::/64", f"{DOC_PREFIX}:255:0::5"),
            ],
        },
    }


CEOS_DATA_PLANE = ceos_data_plane(DEFAULT_MGMT_SUBNET)

RADIUS_BINDS = [
    "../lab/.gen/clients.conf:/etc/raddb/clients.conf:ro",
    "../lab/.gen/clients-radsec.conf:/etc/raddb/clients-radsec.conf:ro",
    "../configs/radius/raddb/radiusd.conf:/etc/raddb/radiusd-log.conf:ro",
    "../configs/radius/raddb/sites-available/tls:/etc/raddb/sites-available/tls:ro",
    "../lab/.gen/pki/server.pem:/etc/raddb/certs/radsec/server.pem:ro",
    "../lab/.gen/pki/ca.pem:/etc/raddb/certs/radsec/ca.pem:ro",
    "../lab/.gen/pki/ceos1-both-client.pem:/etc/raddb/certs/probe/ceos1-both-client.pem:ro",
    "../lab/.gen/pki/ceos1-both-client.key:/etc/raddb/certs/probe/ceos1-both-client.key:ro",
    "../lab/.gen/pki/ceos2-pqc-client.pem:/etc/raddb/certs/probe/ceos2-pqc-client.pem:ro",
    "../lab/.gen/pki/ceos2-pqc-client.key:/etc/raddb/certs/probe/ceos2-pqc-client.key:ro",
    "../lab/.gen/pki/ceos3-qkd-client.pem:/etc/raddb/certs/probe/ceos3-qkd-client.pem:ro",
    "../lab/.gen/pki/ceos3-qkd-client.key:/etc/raddb/certs/probe/ceos3-qkd-client.key:ro",
    "logs/radius:/var/log/radius",
]

SYSLOG_BINDS = [
    "../configs/syslog/syslog-ng.conf:/etc/syslog-ng/syslog-ng.conf:ro",
    "../docker/syslog/openssl-pqc.cnf:/etc/syslog-ng/openssl-pqc.cnf:ro",
    "../lab/.gen/pki/syslog-server.pem:/etc/syslog-ng/certs/server.pem:ro",
    "../lab/.gen/pki/syslog-server.key:/etc/syslog-ng/certs/server.key:ro",
    "../lab/.gen/pki/ca.pem:/etc/syslog-ng/certs/ca.pem:ro",
    "logs/syslog:/var/log/syslog",
]

KME_BINDS = [
    "../lab/.gen/kme-pki:/certs:ro",
]

KME_COMMON_ENV = {
    "HOST": "::",
    "DEFAULT_KEY_SIZE": "256",
    "MAX_KEY_COUNT": "100000",
    "MAX_KEYS_PER_REQUEST": "128",
    "MAX_KEY_SIZE": "1024",
    "MIN_KEY_SIZE": "256",
    "KEY_GEN_SEC_TO_GEN": "30",
    "CA_FILE": "/certs/ca.crt.pem",
    "SAE_CERT": "/certs/sae.crt.pem",
}

KME_NODES: dict[str, dict[str, Any]] = {
    "kme-a": {
        "port": KME_A_PORT,
        "kme_id": KME_A_ID,
        "attached_sae_id": KME_SAE_ID,
        "kme_cert": "/certs/kme-a.crt.pem",
        "kme_key": "/certs/kme-a.key.pem",
        "peer_node": "kme-b",
        "peer_port": KME_B_PORT,
        "sae_client_ips": True,
    },
    "kme-b": {
        "port": KME_B_PORT,
        "kme_id": KME_B_ID,
        "attached_sae_id": KME_B_SAE_ID,
        "kme_cert": "/certs/kme-b.crt.pem",
        "kme_key": "/certs/kme-b.key.pem",
        "peer_node": "kme-a",
        "peer_port": KME_A_PORT,
        "sae_client_ips": True,
        "sae_cert": "/certs/sae-b.crt.pem",
    },
}

KME_PKI_FILES = [
    "ca.crt.pem",
    "kme-a.crt.pem",
    "kme-a.key.pem",
    "kme-b.crt.pem",
    "kme-b.key.pem",
    "sae.crt.pem",
    "sae.key.pem",
    "sae-b.crt.pem",
    "sae-b.key.pem",
    "kme-sae-bundle.pem",
    "kme-sae-b-bundle.pem",
]


def kme_other_kmes(peer_ip: str, peer_port: int) -> str:
    """Return OTHER_KMES URL for a peer KME on the mgmt plane."""
    return f"https://{peer_ip}:{peer_port}"


def kme_sae_client_ips(
    mgmt_ips: dict[str, str],
    *,
    mgmt_ipv6_ips: dict[str, str] | None = None,
) -> str:
    """Return comma-separated mgmt IPs allowed to call the KME SAE API."""
    clients = [mgmt_ips[node] for node in KME_SAE_CLIENT_NODES]
    if mgmt_ipv6_ips is not None:
        clients.extend(mgmt_ipv6_ips[node] for node in KME_SAE_CLIENT_NODES)
    return ",".join(clients)


def kme_env_for_node(
    node: str,
    *,
    mgmt_ips: dict[str, str],
    mgmt_ipv6_ips: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return expected KME container env for a lab node."""
    spec = KME_NODES[node]
    peer = spec["peer_node"]
    env = {
        **KME_COMMON_ENV,
        "PORT": str(spec["port"]),
        "KME_ID": spec["kme_id"],
        "ATTACHED_SAE_ID": spec["attached_sae_id"],
        "OTHER_KMES": kme_other_kmes(mgmt_ips[peer], spec["peer_port"]),
        "KME_CERT": spec["kme_cert"],
        "KME_KEY": spec["kme_key"],
        "SAE_CERT": spec.get("sae_cert", KME_COMMON_ENV["SAE_CERT"]),
    }
    if spec.get("sae_client_ips"):
        env["SAE_CLIENT_IPS"] = kme_sae_client_ips(mgmt_ips, mgmt_ipv6_ips=mgmt_ipv6_ips)
    return env

CEOS_RADSEC_PKI_EXEC = {
    "ceos1-both": (
        'bash -c \'{ echo enable; echo "copy flash:radsec-ca.pem certificate:"; '
        'echo "copy flash:ceos1-both-client.pem certificate:"; '
        'echo "copy flash:ceos1-both-client.key sslkey:"; '
        'echo "copy flash:ceos1-both-eapi.pem certificate:"; '
        'echo "copy flash:ceos1-both-eapi.key sslkey:"; '
        'echo "copy flash:ceos1-both-gnmi.pem certificate:"; '
        'echo "copy flash:ceos1-both-gnmi.key sslkey:"; } | Cli\''
    ),
    "ceos2-pqc": (
        'bash -c \'{ echo enable; echo "copy flash:radsec-ca.pem certificate:"; '
        'echo "copy flash:ceos2-pqc-client.pem certificate:"; '
        'echo "copy flash:ceos2-pqc-client.key sslkey:"; '
        'echo "copy flash:ceos2-pqc-eapi.pem certificate:"; '
        'echo "copy flash:ceos2-pqc-eapi.key sslkey:"; '
        'echo "copy flash:ceos2-pqc-gnmi.pem certificate:"; '
        'echo "copy flash:ceos2-pqc-gnmi.key sslkey:"; } | Cli\''
    ),
    "ceos3-qkd": (
        'bash -c \'{ echo enable; echo "copy flash:radsec-ca.pem certificate:"; '
        'echo "copy flash:ceos3-qkd-client.pem certificate:"; '
        'echo "copy flash:ceos3-qkd-client.key sslkey:"; '
        'echo "copy flash:ceos3-qkd-eapi.pem certificate:"; '
        'echo "copy flash:ceos3-qkd-eapi.key sslkey:"; '
        'echo "copy flash:ceos3-qkd-gnmi.pem certificate:"; '
        'echo "copy flash:ceos3-qkd-gnmi.key sslkey:"; } | Cli\''
    ),
}

CEOS_BINDS = {
    "ceos1-both": [
        "../lab/.gen/pki/radsec-ca.pem:/mnt/flash/radsec-ca.pem:ro",
        "../lab/.gen/pki/ceos1-both-client.pem:/mnt/flash/ceos1-both-client.pem:ro",
        "../lab/.gen/pki/ceos1-both-client.key:/mnt/flash/ceos1-both-client.key:ro",
        "../lab/.gen/pki/ceos1-both-eapi.pem:/mnt/flash/ceos1-both-eapi.pem:ro",
        "../lab/.gen/pki/ceos1-both-eapi.key:/mnt/flash/ceos1-both-eapi.key:ro",
        "../lab/.gen/pki/ceos1-both-gnmi.pem:/mnt/flash/ceos1-both-gnmi.pem:ro",
        "../lab/.gen/pki/ceos1-both-gnmi.key:/mnt/flash/ceos1-both-gnmi.key:ro",
        *CEOS_KME_BINDS,
    ],
    "ceos2-pqc": [
        "../lab/.gen/pki/radsec-ca.pem:/mnt/flash/radsec-ca.pem:ro",
        "../lab/.gen/pki/ceos2-pqc-client.pem:/mnt/flash/ceos2-pqc-client.pem:ro",
        "../lab/.gen/pki/ceos2-pqc-client.key:/mnt/flash/ceos2-pqc-client.key:ro",
        "../lab/.gen/pki/ceos2-pqc-eapi.pem:/mnt/flash/ceos2-pqc-eapi.pem:ro",
        "../lab/.gen/pki/ceos2-pqc-eapi.key:/mnt/flash/ceos2-pqc-eapi.key:ro",
        "../lab/.gen/pki/ceos2-pqc-gnmi.pem:/mnt/flash/ceos2-pqc-gnmi.pem:ro",
        "../lab/.gen/pki/ceos2-pqc-gnmi.key:/mnt/flash/ceos2-pqc-gnmi.key:ro",
    ],
    "ceos3-qkd": [
        "../lab/.gen/pki/radsec-ca.pem:/mnt/flash/radsec-ca.pem:ro",
        "../lab/.gen/pki/ceos3-qkd-client.pem:/mnt/flash/ceos3-qkd-client.pem:ro",
        "../lab/.gen/pki/ceos3-qkd-client.key:/mnt/flash/ceos3-qkd-client.key:ro",
        "../lab/.gen/pki/ceos3-qkd-eapi.pem:/mnt/flash/ceos3-qkd-eapi.pem:ro",
        "../lab/.gen/pki/ceos3-qkd-eapi.key:/mnt/flash/ceos3-qkd-eapi.key:ro",
        "../lab/.gen/pki/ceos3-qkd-gnmi.pem:/mnt/flash/ceos3-qkd-gnmi.pem:ro",
        "../lab/.gen/pki/ceos3-qkd-gnmi.key:/mnt/flash/ceos3-qkd-gnmi.key:ro",
        *CEOS_KME_BINDS,
    ],
}

PKI_FILES = [
    "ca.pem",
    "radsec-ca.pem",
    "server.pem",
    "ceos1-both-client.pem",
    "ceos1-both-client.key",
    "ceos1-both-eapi.pem",
    "ceos1-both-eapi.key",
    "ceos1-both-gnmi.pem",
    "ceos1-both-gnmi.key",
    "ceos2-pqc-client.pem",
    "ceos2-pqc-client.key",
    "ceos2-pqc-eapi.pem",
    "ceos2-pqc-eapi.key",
    "ceos2-pqc-gnmi.pem",
    "ceos2-pqc-gnmi.key",
    "ceos3-qkd-client.pem",
    "ceos3-qkd-client.key",
    "ceos3-qkd-eapi.pem",
    "ceos3-qkd-eapi.key",
    "ceos3-qkd-gnmi.pem",
    "ceos3-qkd-gnmi.key",
    "syslog-server.pem",
    "syslog-server.key",
]

CEOS_STARTUP_CONFIGS = {
    "ceos1-both": "../lab/.gen/ceos1-both.cfg",
    "ceos2-pqc": "../lab/.gen/ceos2-pqc.cfg",
    "ceos3-qkd": "../lab/.gen/ceos3-qkd.cfg",
}

CONFIG_PATHS = {
    "ceos1-both": REPO_ROOT / "configs" / "ceos" / "ceos1-both.cfg.in",
    "ceos2-pqc": REPO_ROOT / "configs" / "ceos" / "ceos2-pqc.cfg.in",
    "ceos3-qkd": REPO_ROOT / "configs" / "ceos" / "ceos3-qkd.cfg.in",
    "clients": REPO_ROOT / "configs" / "radius" / "raddb" / "clients.conf.in",
    "clients_radsec": REPO_ROOT / "configs" / "radius" / "raddb" / "clients-radsec.conf.in",
    "tls_site": REPO_ROOT / "configs" / "radius" / "raddb" / "sites-available" / "tls",
    "radiusd": REPO_ROOT / "configs" / "radius" / "raddb" / "radiusd.conf",
    "dockerfile": REPO_ROOT / "docker" / "radius" / "Dockerfile",
    "syslog_dockerfile": REPO_ROOT / "docker" / "syslog" / "Dockerfile",
    "syslog_conf": REPO_ROOT / "configs" / "syslog" / "syslog-ng.conf",
    "kme_dockerfile": REPO_ROOT / "docker" / "kme" / "Dockerfile",
    "eap": REPO_ROOT / "configs" / "radius" / "raddb" / "mods-available" / "eap",
}


def resolve_topo_path(relative_path: str, topo_dir: Path | None = None) -> Path:
    """Resolve a topology-relative path the way Containerlab does (base = topo file dir)."""
    base = topo_dir or (REPO_ROOT / "lab")
    return (base / relative_path).resolve()


def validate_topo_host_paths(repo_root: Path | None = None) -> list[str]:
    """Ensure startup-config and bind host paths exist relative to the topology file."""
    errors: list[str] = []
    root = repo_root or REPO_ROOT
    topo_dir = root / "lab"

    for ceos, rel_path in CEOS_STARTUP_CONFIGS.items():
        host_path = resolve_topo_path(rel_path, topo_dir)
        if not host_path.is_file():
            errors.append(f"{ceos} startup-config host path missing: {host_path}")

    for bind in RADIUS_BINDS:
        host_path = resolve_topo_path(bind.split(":", 1)[0], topo_dir)
        if not host_path.exists():
            errors.append(f"radius bind host path missing: {host_path}")

    for bind in KME_BINDS:
        host_path = resolve_topo_path(bind.split(":", 1)[0], topo_dir)
        if not host_path.exists():
            errors.append(f"kme bind host path missing: {host_path}")

    kme_pki_dir = root / "lab" / ".gen" / "kme-pki"
    for name in KME_PKI_FILES:
        if not (kme_pki_dir / name).is_file():
            errors.append(f"missing lab/.gen/kme-pki/{name} (run make gen-topo)")

    for ceos, binds in CEOS_BINDS.items():
        for bind in binds:
            host_path = resolve_topo_path(bind.split(":", 1)[0], topo_dir)
            if not host_path.exists():
                errors.append(f"{ceos} bind host path missing: {host_path}")

    pki_dir = root / "lab" / ".gen" / "pki"
    for name in PKI_FILES:
        if not (pki_dir / name).is_file():
            errors.append(f"missing lab/.gen/pki/{name} (run make gen-topo)")

    return errors


def load_topology(path: Path | None = None) -> dict[str, Any]:
    """Load and parse the Containerlab topology YAML."""
    topo_path = path or TOPOLOGY_PATH
    with topo_path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{topo_path}: expected mapping at root, got {type(data).__name__}")
    return data


def _host_exec_commands(node_cfg: dict[str, Any]) -> list[str]:
    exec_cmds = node_cfg.get("exec", [])
    if exec_cmds is None:
        return []
    if not isinstance(exec_cmds, list):
        raise ValueError("host exec must be a list")
    return [str(cmd) for cmd in exec_cmds]


def validate_mgmt_topology_nodes(nodes: dict[str, Any]) -> list[str]:
    """Validate mgmt nodes use docker mgmt (no bridge node or eth0 links)."""
    errors: list[str] = []
    if MGMT_BRIDGE in nodes:
        errors.append(
            f"topology must not declare {MGMT_BRIDGE} as a node "
            f"(mgmt.bridge names the host bridge backing docker mgmt)"
        )
    for node in MGMT_LINUX_NODES:
        node_cfg = nodes.get(node, {})
        if node_cfg.get("network-mode") == "none":
            errors.append(f"{node} must use default docker mgmt (do not set network-mode: none)")
        exec_text = "\n".join(_host_exec_commands(node_cfg))
        if "dev eth0" in exec_text:
            errors.append(f"{node} must not configure eth0 via exec (docker mgmt assigns it)")
    return errors


def validate_host_data_plane(nodes: dict[str, Any]) -> list[str]:
    """Validate host exec stanzas match the locked data-plane contract."""
    errors: list[str] = []

    for host, expected in HOST_DATA_PLANE.items():
        node_cfg = nodes.get(host)
        if node_cfg is None:
            continue

        exec_cmds = _host_exec_commands(node_cfg)
        exec_text = "\n".join(exec_cmds)

        if f"ip addr add {expected['addr']} dev eth1" not in exec_text:
            errors.append(f"{host} exec must configure {expected['addr']} on eth1")
        if f"ip route replace default via {expected['gateway']} dev eth1" not in exec_text:
            errors.append(f"{host} exec must use default gateway {expected['gateway']}")
        if f"ip -6 addr add {expected['addr6']} dev eth1" not in exec_text:
            errors.append(f"{host} exec must configure {expected['addr6']} on eth1")
        if f"ip -6 route replace default via {expected['gateway6']} dev eth1" not in exec_text:
            errors.append(f"{host} exec must use default IPv6 gateway {expected['gateway6']}")

    return errors


def _ceos_config_text(name: str, repo_root: Path | None = None) -> str:
    root = repo_root or REPO_ROOT
    path = root / "configs" / "ceos" / f"{name}.cfg"
    if not path.is_file():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8")


def validate_ceos_configs(
    repo_root: Path | None = None,
    *,
    mgmt_subnet: str | None = None,
    mgmt_ipv6_subnet: str | None = None,
) -> list[str]:
    """Validate rendered cEOS startup configs against mgmt and data-plane contract."""
    from lab.syslog_checks import cleartext_syslog_lines

    errors: list[str] = []
    root = repo_root or REPO_ROOT
    expected_plane = ceos_data_plane(mgmt_subnet, mgmt_ipv6_subnet=mgmt_ipv6_subnet)
    mgmt_ips = mgmt_ips_for_subnet(mgmt_subnet)
    mgmt_ipv6 = mgmt_ipv6_ips_for_subnet(mgmt_ipv6_subnet)
    radius_ip = mgmt_ipv6["radius"]
    syslog_ipv4 = mgmt_ips["syslog"]
    syslog_ipv6 = mgmt_ipv6["syslog"]
    kme_a_ip = mgmt_ips["kme-a"]
    kme_b_ip = mgmt_ips["kme-b"]

    for ceos, expected in expected_plane.items():
        path = root / "lab" / ".gen" / f"{ceos}.cfg"
        if not path.is_file():
            errors.append(f"missing {path.relative_to(root)} (run make gen-topo)")
            continue

        text = path.read_text(encoding="utf-8")
        if "vrf instance MGMT" not in text:
            errors.append(f"{ceos}.cfg must define vrf instance MGMT")
        if f"ip address {expected['mgmt_ip']}" not in text:
            errors.append(f"{ceos}.cfg Management0 must have {expected['mgmt_ip']}")
        if f"ip route vrf MGMT 0.0.0.0/0 {expected['mgmt_gateway']}" not in text:
            errors.append(
                f"{ceos}.cfg must use mgmt gateway {expected['mgmt_gateway']}"
            )
        if f"ipv6 address {expected['mgmt_ip6']}" not in text:
            errors.append(f"{ceos}.cfg Management0 must have {expected['mgmt_ip6']}")
        if f"ipv6 route vrf MGMT ::/0 {expected['mgmt_gateway6']}" not in text:
            errors.append(
                f"{ceos}.cfg must use mgmt IPv6 gateway {expected['mgmt_gateway6']}"
            )
        if f"ip address {expected['eth1']}" not in text:
            errors.append(f"{ceos}.cfg Ethernet1 must have {expected['eth1']}")
        if f"ipv6 address {expected['eth1_ipv6']}" not in text:
            errors.append(f"{ceos}.cfg Ethernet1 must have {expected['eth1_ipv6']}")
        if "eth3" in expected and f"ip address {expected['eth3']}" not in text:
            errors.append(f"{ceos}.cfg Ethernet3 must have {expected['eth3']}")
        if "eth3_ipv6" in expected and f"ipv6 address {expected['eth3_ipv6']}" not in text:
            errors.append(f"{ceos}.cfg Ethernet3 must have {expected['eth3_ipv6']}")
        if f"ip address {expected['eth8']}" not in text:
            errors.append(f"{ceos}.cfg Ethernet8 must have {expected['eth8']}")
        if f"ipv6 address {expected['eth8_ipv6']}" not in text:
            errors.append(f"{ceos}.cfg Ethernet8 must have {expected['eth8_ipv6']}")

        for prefix, nexthop in expected["static_routes"]:
            if f"ip route {prefix} {nexthop}" not in text:
                errors.append(f"{ceos}.cfg must route {prefix} via {nexthop}")
        for prefix, nexthop in expected["static_routes6"]:
            if f"ipv6 route {prefix} {nexthop}" not in text:
                errors.append(f"{ceos}.cfg must route {prefix} via {nexthop}")

        if f"radius-server host {radius_ip} vrf MGMT tls ssl-profile {SSL_PROFILE}" not in text:
            errors.append(f"{ceos}.cfg must configure RadSec server in MGMT VRF over IPv6")
        if f"radius-server host {mgmt_ips['radius']} vrf MGMT" in text:
            errors.append(f"{ceos}.cfg must not configure legacy IPv4 RadSec server")
        if "ssl profile RADSEC" not in text:
            errors.append(f"{ceos}.cfg must define ssl profile RADSEC")
        if "tls versions 1.3" not in text:
            errors.append(f"{ceos}.cfg must restrict ssl profile to TLS 1.3")
        security = text.split("management security", 1)[-1].split("\n!", 1)[0]
        for profile_name, block in re.findall(
            r"^   ssl profile (\S+)(.*?)(?=^   ssl profile |\Z)",
            security,
            flags=re.MULTILINE | re.DOTALL,
        ):
            if profile_name == SYSLOG_SSL_PROFILE:
                if f"key-establishment-group {SYSLOG_TLS_PQC_SAFE_EOS_GROUPS}" not in block:
                    errors.append(
                        f"{ceos}.cfg SYSLOG ssl profile must use PQC-safe groups "
                        f"{SYSLOG_TLS_PQC_SAFE_EOS_GROUPS!r}"
                    )
                continue
            if f"key-establishment-group {TLS_PQC_EOS_GROUPS}" not in block:
                errors.append(
                    f"{ceos}.cfg ssl profile {profile_name} must use PQC-hybrid group "
                    f"{TLS_PQC_EOS_GROUPS!r} only"
                )
            if re.search(
                r"key-establishment-group\s+\S*(?:ecdh_x25519|secp256r1)",
                block,
            ):
                errors.append(
                    f"{ceos}.cfg ssl profile {profile_name} must not list classical "
                    "TLS fallbacks (PQC-hybrid only)"
                )
        if f"server {radius_ip} tls vrf MGMT" not in text:
            errors.append(f"{ceos}.cfg aaa group must use RadSec transport in MGMT VRF")
        if "logging vrf MGMT" not in text:
            errors.append(f"{ceos}.cfg must configure remote syslog in vrf MGMT")
        for syslog_ip in (syslog_ipv4, syslog_ipv6):
            if (
                f"logging vrf MGMT host {syslog_ip} {SYSLOG_PORT} protocol tls ssl-profile {SYSLOG_SSL_PROFILE}"
                not in text
            ):
                errors.append(
                    f"{ceos}.cfg must forward syslog to {syslog_ip}:{SYSLOG_PORT} via TLS "
                    f"profile {SYSLOG_SSL_PROFILE}"
                )
        logging_section = "\n".join(
            line for line in text.splitlines() if line.strip().startswith("logging")
        )
        cleartext = cleartext_syslog_lines(logging_section)
        if cleartext:
            errors.append(
                f"{ceos}.cfg must not configure cleartext syslog hosts: {cleartext!r}"
            )
        if "logging trap informational" not in text:
            errors.append(f"{ceos}.cfg must trap informational syslog messages")
        if f"ssl profile {SYSLOG_SSL_PROFILE}" not in text:
            errors.append(f"{ceos}.cfg must define ssl profile {SYSLOG_SSL_PROFILE}")
        if f"ssl profile {EAPI_SSL_PROFILE}" not in text:
            errors.append(f"{ceos}.cfg must define ssl profile {EAPI_SSL_PROFILE}")
        if f"protocol https ssl profile {EAPI_SSL_PROFILE}" not in text:
            errors.append(f"{ceos}.cfg must enable eAPI HTTPS with ssl profile {EAPI_SSL_PROFILE}")
        if f"certificate {ceos}-eapi.pem key {ceos}-eapi.key" not in text:
            errors.append(f"{ceos}.cfg must reference per-switch eAPI certificate")
        if f"ssl profile {GNMI_SSL_PROFILE}" not in text:
            errors.append(f"{ceos}.cfg must define ssl profile {GNMI_SSL_PROFILE}")
        if f"ssl profile {GNMI_SSL_PROFILE}" not in text.split("management api gnmi", 1)[-1]:
            errors.append(f"{ceos}.cfg gNMI transport must reference ssl profile {GNMI_SSL_PROFILE}")
        if f"certificate {ceos}-gnmi.pem key {ceos}-gnmi.key" not in text:
            errors.append(f"{ceos}.cfg must reference per-switch gNMI certificate")
        if "management api gnmi" not in text:
            errors.append(f"{ceos}.cfg must enable management api gnmi")
        if "transport grpc default" not in text:
            errors.append(f"{ceos}.cfg must configure gNMI grpc default transport")
        if f"ssl profile {RESTCONF_SSL_PROFILE}" not in text:
            errors.append(f"{ceos}.cfg must define ssl profile {RESTCONF_SSL_PROFILE}")
        if "management api restconf" not in text:
            errors.append(f"{ceos}.cfg must enable management api restconf")
        if f"ssl profile {RESTCONF_SSL_PROFILE}" not in text.split("management api restconf", 1)[-1]:
            errors.append(f"{ceos}.cfg RESTCONF transport must reference ssl profile {RESTCONF_SSL_PROFILE}")
        if "management api eos-sdk-rpc" not in text:
            errors.append(f"{ceos}.cfg must enable management api eos-sdk-rpc")
        if f"ssl profile {GNMI_SSL_PROFILE}" not in text.split("management api eos-sdk-rpc", 1)[-1]:
            errors.append(f"{ceos}.cfg eos-sdk-rpc transport must reference ssl profile {GNMI_SSL_PROFILE}")
        eossdkrpc = text.split("management api eos-sdk-rpc", 1)[-1].split("!", 1)[0]
        if "local interface Management0" not in eossdkrpc:
            errors.append(f"{ceos}.cfg eos-sdk-rpc transport must bind local interface Management0")
        if "service all" not in eossdkrpc:
            errors.append(f"{ceos}.cfg eos-sdk-rpc transport must enable service all")
        if "no disabled" not in eossdkrpc:
            errors.append(f"{ceos}.cfg eos-sdk-rpc transport must be enabled (no disabled)")
        syslog_profile = security.split(f"ssl profile {SYSLOG_SSL_PROFILE}", 1)[-1].split("!", 1)[0]
        if f"certificate {ceos}-client.pem key {ceos}-client.key" not in syslog_profile:
            errors.append(f"{ceos}.cfg SYSLOG ssl profile must use per-switch client certificate")
        if "trust certificate radsec-ca.pem" not in syslog_profile:
            errors.append(f"{ceos}.cfg SYSLOG ssl profile must trust radsec-ca.pem")
        gnmi_profile = security.split("ssl profile GNMI", 1)[-1].split("!", 1)[0]
        if "trust certificate radsec-ca.pem" not in gnmi_profile:
            errors.append(f"{ceos}.cfg GNMI ssl profile must trust radsec-ca.pem for mTLS")
        restconf_profile = security.split(f"ssl profile {RESTCONF_SSL_PROFILE}", 1)[-1].split("!", 1)[0]
        if "trust certificate radsec-ca.pem" not in restconf_profile:
            errors.append(f"{ceos}.cfg RESTCONF ssl profile must trust radsec-ca.pem for mTLS")
        if f"ip access-list {CONTROL_PLANE_ACL}" not in text:
            errors.append(f"{ceos}.cfg must define control-plane ACL {CONTROL_PLANE_ACL}")
        if f"permit tcp any any eq {RESTCONF_PORT}" not in text:
            errors.append(
                f"{ceos}.cfg control-plane ACL must permit TCP {RESTCONF_PORT} (RESTCONF)"
            )
        if f"permit tcp any any eq {EOSSDKRPC_PORT}" not in text:
            errors.append(
                f"{ceos}.cfg control-plane ACL must permit TCP {EOSSDKRPC_PORT} (eos-sdk-rpc)"
            )
        if f"ip access-group {CONTROL_PLANE_ACL} vrf MGMT in" not in text:
            errors.append(
                f"{ceos}.cfg must apply {CONTROL_PLANE_ACL} on system control-plane vrf MGMT"
            )
        if f"ipv6 access-group {CONTROL_PLANE_ACL}-v6 vrf MGMT in" not in text:
            errors.append(
                f"{ceos}.cfg must apply {CONTROL_PLANE_ACL}-v6 on system control-plane vrf MGMT"
            )
        if "copy flash:" in text:
            errors.append(f"{ceos}.cfg must not use copy flash in startup-config (use containerlab exec)")
        if "aaa group server radius RADIUS" not in text:
            errors.append(f"{ceos}.cfg must define aaa group server radius RADIUS")
        if "management ssh" not in text:
            errors.append(f"{ceos}.cfg must configure management ssh")
        if f"key-exchange {SSH_PQC_KEX}" not in text:
            errors.append(f"{ceos}.cfg must configure SSH PQC key exchange ({SSH_PQC_KEX})")
        if f"cipher {SSH_PQC_CIPHERS}" not in text:
            errors.append(f"{ceos}.cfg must configure SSH PQC ciphers")
        if f"mac {SSH_PQC_MACS}" not in text:
            errors.append(f"{ceos}.cfg must configure SSH PQC MAC algorithms")
        ssh_vrf_enabled = re.search(
            r"management ssh.*?vrf MGMT\s+no shutdown",
            text,
            flags=re.DOTALL,
        )
        if not ssh_vrf_enabled:
            errors.append(f"{ceos}.cfg must enable SSH in vrf MGMT")
        ssh_default_shutdown = re.search(
            r"management ssh.*?^\s+shutdown\s*$",
            text,
            flags=re.DOTALL | re.MULTILINE,
        )
        if not ssh_default_shutdown:
            errors.append(f"{ceos}.cfg must disable SSH on the default VRF (shutdown)")

        if ceos in CEOS_MACSEC_NODES:
            if "dot1x system-auth-control" not in text:
                errors.append(f"{ceos}.cfg must enable dot1x system-auth-control")
            if f"profile {MACSEC_PROFILE}" not in text:
                errors.append(f"{ceos}.cfg must define mac security profile {MACSEC_PROFILE}")
            if "key source dot1x" not in text:
                errors.append(f"{ceos}.cfg mac security profile must use key source dot1x")
            if f"mac security profile {MACSEC_PROFILE}" not in text:
                errors.append(f"{ceos}.cfg Ethernet1 must apply mac security profile {MACSEC_PROFILE}")

        if ceos == "ceos1-both":
            if "aaa authentication dot1x default group RADIUS" not in text:
                errors.append(f"{ceos}.cfg must authenticate dot1x via RadSec group RADIUS")
            if "aaa accounting dot1x default start-stop group RADIUS" not in text:
                errors.append(f"{ceos}.cfg must account dot1x via RadSec group RADIUS")
            if "dot1x pae authenticator" not in text:
                errors.append(f"{ceos}.cfg Ethernet1 must act as dot1x authenticator")
            if "dot1x port-control auto" not in text:
                errors.append(f"{ceos}.cfg Ethernet1 must use dot1x port-control auto")
            if "dot1x reauthentication" not in text:
                errors.append(f"{ceos}.cfg Ethernet1 must enable dot1x reauthentication")
            if f"dot1x timeout reauth-period {DOT1X_REAUTH_PERIOD_SEC}" not in text:
                errors.append(
                    f"{ceos}.cfg Ethernet1 must set dot1x timeout reauth-period "
                    f"{DOT1X_REAUTH_PERIOD_SEC}"
                )
        elif ceos == "ceos2-pqc":
            if f"supplicant profile {DOT1X_SUPPLICANT_PROFILE}" not in text:
                errors.append(
                    f"{ceos}.cfg must define dot1x supplicant profile {DOT1X_SUPPLICANT_PROFILE}"
                )
            if f"identity {DOT1X_EAP_IDENTITY}" not in text:
                errors.append(f"{ceos}.cfg dot1x supplicant must use identity {DOT1X_EAP_IDENTITY}")
            if "eap-method tls" not in text:
                errors.append(f"{ceos}.cfg dot1x supplicant must use eap-method tls")
            if f"ssl profile {DOT1X_EAP_SSL_PROFILE}" not in text:
                errors.append(
                    f"{ceos}.cfg dot1x supplicant must reference ssl profile {DOT1X_EAP_SSL_PROFILE}"
                )
            if f"ssl profile {DOT1X_EAP_SSL_PROFILE}" not in text.split("management security", 1)[-1]:
                errors.append(f"{ceos}.cfg must define ssl profile {DOT1X_EAP_SSL_PROFILE}")
            if f"dot1x pae supplicant {DOT1X_SUPPLICANT_PROFILE}" not in text:
                errors.append(
                    f"{ceos}.cfg Ethernet1 must enable dot1x supplicant {DOT1X_SUPPLICANT_PROFILE}"
                )
        elif ceos == "ceos3-qkd":
            if "dot1x" in text:
                errors.append(f"{ceos}.cfg must not configure dot1x on the QuaDRA link")

        if ceos in CEOS_QUADRA_NODES:
            profile = (
                QUADRA_MACSEC_PROFILE_MASTER
                if ceos == "ceos1-both"
                else QUADRA_MACSEC_PROFILE_SLAVE
            )
            intf = QUADRA_MACSEC_INTF[ceos]
            if f"profile {profile}" not in text:
                errors.append(f"{ceos}.cfg must define QuaDRA mac security profile {profile}")
            if "key source sak static" not in text:
                errors.append(f"{ceos}.cfg QuaDRA profile must use key source sak static")
            if "cipher aes256-gcm-xpn" not in text:
                errors.append(f"{ceos}.cfg QuaDRA profile must use aes256-gcm-xpn cipher")
            if f"an 0 key {QUADRA_KEY_RX}" not in text:
                errors.append(f"{ceos}.cfg QuaDRA profile must include rx placeholder key")
            if f"an 0 key {QUADRA_KEY_TX}" not in text:
                errors.append(f"{ceos}.cfg QuaDRA profile must include tx placeholder key")
            if f"mac security profile {profile}" not in text.split(f"interface {intf}", 1)[-1]:
                errors.append(f"{ceos}.cfg {intf} must apply mac security profile {profile}")
            if "daemon quadra" not in text:
                errors.append(f"{ceos}.cfg must define daemon quadra")
            if "exec /usr/bin/quadra" not in text:
                errors.append(f"{ceos}.cfg daemon quadra must exec /usr/bin/quadra")
            quadra_block = text.split("daemon quadra", 1)[-1].split("!", 1)[0]
            if "no shutdown" in quadra_block:
                errors.append(f"{ceos}.cfg daemon quadra must remain shutdown until manually enabled")
            if "shutdown" not in quadra_block:
                errors.append(f"{ceos}.cfg daemon quadra must be shutdown (agent not auto-started)")
            if f"option macsec-intf value {intf}" not in text:
                errors.append(f"{ceos}.cfg daemon quadra must set macsec-intf {intf}")
            if f"option peer value {QUADRA_PEER_IP[ceos]}" not in text:
                errors.append(
                    f"{ceos}.cfg daemon quadra must set peer {QUADRA_PEER_IP[ceos]}"
                )
            if "option kme-vrf value MGMT" not in text:
                errors.append(f"{ceos}.cfg daemon quadra must set kme-vrf MGMT")
            if "option cacert value /mnt/flash/kme-ca.crt.pem" not in text:
                errors.append(f"{ceos}.cfg daemon quadra must reference kme-ca.crt.pem")
            bundle = QUADRA_KME_BUNDLE[ceos]
            if f"option cert value /mnt/flash/{bundle}" not in text:
                errors.append(f"{ceos}.cfg daemon quadra must reference /mnt/flash/{bundle}")
            if ceos == "ceos1-both":
                if f"option kme value {kme_a_ip}:{KME_A_PORT}" not in text:
                    errors.append(
                        f"{ceos}.cfg daemon quadra must point kme at kme-a "
                        f"({kme_a_ip}:{KME_A_PORT})"
                    )
                if f"option peer-sae value {KME_B_SAE_ID}" not in text:
                    errors.append(f"{ceos}.cfg daemon quadra must set peer-sae {KME_B_SAE_ID}")
                if "option peer-mode value slave" not in text:
                    errors.append(
                        f"{ceos}.cfg daemon quadra must use peer-mode slave (master role)"
                    )
                if (
                    f"option recovery-keys value {QUADRA_KEY_RX},{QUADRA_KEY_TX}"
                    not in text
                ):
                    errors.append(f"{ceos}.cfg daemon quadra must set master recovery-keys")
            else:
                if f"option kme value {kme_b_ip}:{KME_B_PORT}" not in text:
                    errors.append(
                        f"{ceos}.cfg daemon quadra must point kme at kme-b "
                        f"({kme_b_ip}:{KME_B_PORT})"
                    )
                if f"option peer-sae value {KME_SAE_ID}" not in text:
                    errors.append(f"{ceos}.cfg daemon quadra must set peer-sae {KME_SAE_ID}")
                if "option peer-mode value master" not in text:
                    errors.append(
                        f"{ceos}.cfg daemon quadra must use peer-mode master (slave role)"
                    )
                if (
                    f"option recovery-keys value {QUADRA_KEY_TX},{QUADRA_KEY_RX}"
                    not in text
                ):
                    errors.append(f"{ceos}.cfg daemon quadra must set slave recovery-keys")

    return errors


def validate_syslog_configs(repo_root: Path | None = None) -> list[str]:
    """Validate syslog-ng image and collector configuration."""
    errors: list[str] = []
    root = repo_root or REPO_ROOT

    dockerfile_path = root / "docker" / "syslog" / "Dockerfile"
    syslog_conf_path = root / "configs" / "syslog" / "syslog-ng.conf"
    openssl_cnf_path = root / "docker" / "syslog" / "openssl-pqc.cnf"

    if not dockerfile_path.is_file():
        errors.append(f"missing {dockerfile_path.relative_to(root)}")
    if not syslog_conf_path.is_file():
        errors.append(f"missing {syslog_conf_path.relative_to(root)}")
    if not openssl_cnf_path.is_file():
        errors.append(f"missing {openssl_cnf_path.relative_to(root)}")

    if syslog_conf_path.is_file():
        syslog_conf = syslog_conf_path.read_text(encoding="utf-8")
        if f"port({SYSLOG_PORT})" not in syslog_conf:
            errors.append(f"syslog-ng.conf must listen on port {SYSLOG_PORT}")
        if 'transport("tls")' not in syslog_conf:
            errors.append("syslog-ng.conf must use TLS transport")
        if 'ip("::")' not in syslog_conf:
            errors.append('syslog-ng.conf must listen on all interfaces via ip("::")')
        if "ip-protocol(6)" not in syslog_conf.replace(" ", ""):
            errors.append("syslog-ng.conf must set ip-protocol(6) for dual-stack TLS syslog")
        if re.search(r"port\((514|601)\)", syslog_conf):
            errors.append("syslog-ng.conf must not listen on cleartext syslog ports 514/601")

    if openssl_cnf_path.is_file():
        openssl_cnf = openssl_cnf_path.read_text(encoding="utf-8")
        if TLS_PQC_GROUP not in openssl_cnf:
            errors.append(f"syslog openssl-pqc.cnf must advertise {TLS_PQC_GROUP}")
        if SYSLOG_TLS_PQC_SAFE_OPENSSL_GROUPS not in openssl_cnf.replace(" ", ""):
            errors.append(
                "syslog openssl-pqc.cnf must use PQC-safe groups "
                f"({SYSLOG_TLS_PQC_SAFE_OPENSSL_GROUPS!r})"
            )
        if "MinProtocol = TLSv1.3" not in openssl_cnf:
            errors.append("syslog openssl-pqc.cnf must require TLS 1.3")

    if dockerfile_path.is_file():
        dockerfile = dockerfile_path.read_text(encoding="utf-8")
        for fragment in (
            "openssl-3.5.7",
            "SYSLOG_NG_VERSION=4.8.1",
            "openssl-pqc.cnf",
            "OPENSSL_CONF=/etc/syslog-ng/openssl-pqc.cnf",
            "syslog-ng.conf",
        ):
            if fragment not in dockerfile:
                errors.append(f"syslog Dockerfile must contain: {fragment!r}")

    pki_dir = root / "lab" / ".gen" / "pki"
    for name in ("syslog-server.pem", "syslog-server.key", "ca.pem"):
        if not (pki_dir / name).is_file():
            errors.append(f"missing lab/.gen/pki/{name} (run make gen-topo)")

    return errors


def validate_radius_configs(
    repo_root: Path | None = None,
    *,
    mgmt_subnet: str | None = None,
    mgmt_ipv6_subnet: str | None = None,
) -> list[str]:
    """Validate FreeRADIUS client and logging configuration."""
    errors: list[str] = []
    root = repo_root or REPO_ROOT
    mgmt_ipv6 = mgmt_ipv6_ips_for_subnet(mgmt_ipv6_subnet)

    clients_path = root / "lab" / ".gen" / "clients.conf"
    clients_radsec_path = root / "lab" / ".gen" / "clients-radsec.conf"
    tls_site_path = root / "configs" / "radius" / "raddb" / "sites-available" / "tls"
    radiusd_path = root / "configs" / "radius" / "raddb" / "radiusd.conf"
    dockerfile_path = root / "docker" / "radius" / "Dockerfile"

    if not clients_radsec_path.is_file():
        errors.append("missing lab/.gen/clients-radsec.conf (run make gen-topo)")
    else:
        clients_radsec = clients_radsec_path.read_text(encoding="utf-8")
        for ceos, ip in (
            ("ceos1-both", mgmt_ipv6["ceos1-both"]),
            ("ceos2-pqc", mgmt_ipv6["ceos2-pqc"]),
            ("ceos3-qkd", mgmt_ipv6["ceos3-qkd"]),
        ):
            block = re.search(rf"client\s+{ceos}\s*\{{([^}}]+)\}}", clients_radsec, re.DOTALL)
            if block is None:
                errors.append(f"clients-radsec.conf must define client {ceos}")
                continue
            body = block.group(1)
            if f"ipv6addr  = {ip}" not in body and f"ipv6addr = {ip}" not in body:
                errors.append(f"clients-radsec.conf {ceos} ipv6addr must be {ip}")
            if "ipaddr" in body:
                errors.append(f"clients-radsec.conf {ceos} must use ipv6addr, not ipaddr")
            if "proto   = tls" not in body and "proto = tls" not in body:
                errors.append(f"clients-radsec.conf {ceos} must use proto tls")
            if f"secret  = {RADSEC_SECRET}" not in body and f"secret = {RADSEC_SECRET}" not in body:
                errors.append(f"clients-radsec.conf {ceos} secret must be {RADSEC_SECRET}")
            if "require_message_authenticator = true" not in body:
                errors.append(f"clients-radsec.conf {ceos} must set require_message_authenticator")
            if "limit_proxy_state = true" not in body:
                errors.append(f"clients-radsec.conf {ceos} must set limit_proxy_state")

    eap_path = root / "configs" / "radius" / "raddb" / "mods-available" / "eap"
    authorize_path = root / "configs" / "radius" / "raddb" / "mods-config" / "files" / "authorize"

    if not eap_path.is_file():
        errors.append("missing configs/radius/raddb/mods-available/eap")
    else:
        eap = eap_path.read_text(encoding="utf-8")
        if "/etc/raddb/certs/radsec/server.pem" not in eap:
            errors.append("eap module must reference RadSec server certificate")
        if 'tls_min_version = "1.3"' not in eap:
            errors.append("eap module must restrict TLS to 1.3")

    if not authorize_path.is_file():
        errors.append("missing configs/radius/raddb/mods-config/files/authorize")
    else:
        authorize = authorize_path.read_text(encoding="utf-8")
        if "DEFAULT Service-Type == NAS-Prompt-User, Auth-Type := Accept" not in authorize:
            errors.append(
                "authorize must Accept only test aaa (NAS-Prompt-User), not dot1x EAP"
            )
        if "DEFAULT Auth-Type := Accept" in authorize:
            errors.append("authorize must not blanket Accept (breaks dot1x EAP-TLS / MPPE)")
        if "Auth-Type := EAP" in authorize:
            errors.append("authorize must not set blanket Auth-Type EAP (use eap module in default site)")

    macsec_dot1x_path = root / "configs" / "radius" / "raddb" / "policy.d" / "macsec-dot1x"
    if not macsec_dot1x_path.is_file():
        errors.append("missing configs/radius/raddb/policy.d/macsec-dot1x")
    else:
        macsec_dot1x = macsec_dot1x_path.read_text(encoding="utf-8")
        if "EAP-Key-Name := &reply:EAP-Session-Id" not in macsec_dot1x:
            errors.append("macsec-dot1x policy must copy EAP-Session-Id to EAP-Key-Name")
        if f"Session-Timeout := {DOT1X_REAUTH_PERIOD_SEC}" not in macsec_dot1x:
            errors.append(
                f"macsec-dot1x policy must set Session-Timeout := {DOT1X_REAUTH_PERIOD_SEC}"
            )
        if "Termination-Action := RADIUS-Request" not in macsec_dot1x:
            errors.append("macsec-dot1x policy must set Termination-Action := RADIUS-Request")

    if not tls_site_path.is_file():
        errors.append("missing configs/radius/raddb/sites-available/tls")
    else:
        tls_site = tls_site_path.read_text(encoding="utf-8")
        if 'tls_min_version = "1.3"' not in tls_site:
            errors.append("tls site must set tls_min_version 1.3")
        if f"port = {RADSEC_PORT}" not in tls_site:
            errors.append(f"tls site must listen on port {RADSEC_PORT}")
        if "ipv6addr = ::" not in tls_site:
            errors.append("tls site must listen on IPv6 (::) for RadSec")
        if "require_client_cert = yes" not in tls_site:
            errors.append("tls site must require client certificates")

    if not clients_path.is_file():
        errors.append("missing lab/.gen/clients.conf (run make gen-topo)")
    else:
        clients = clients_path.read_text(encoding="utf-8")
        if "172.17.0.0/16" not in clients:
            errors.append("clients.conf must include dockernet client 172.17.0.0/16")
        if "client ceos1-both" in clients or "client ceos2-pqc" in clients or "client ceos3-qkd" in clients:
            errors.append("clients.conf must not define plain UDP ceos clients (use clients-radsec.conf)")

    if not radiusd_path.is_file():
        errors.append("missing configs/radius/raddb/radiusd.conf")
    else:
        radiusd = radiusd_path.read_text(encoding="utf-8")
        if "logdir = /var/log/radius" not in radiusd:
            errors.append("radiusd.conf must set logdir = /var/log/radius for clab bind mount")
        if "/var/log/radius/radius.log" not in radiusd:
            errors.append("radiusd.conf must log to /var/log/radius/radius.log")
        if "auth = yes" not in radiusd:
            errors.append("radiusd.conf must enable auth logging (auth = yes)")

    if not dockerfile_path.is_file():
        errors.append("missing docker/radius/Dockerfile")
    else:
        dockerfile = dockerfile_path.read_text(encoding="utf-8")
        for fragment in (
            "ARG FREERADIUS_VERSION=release_3_2_6",
            "ARG OPENSSL_VERSION=openssl-3.5.7",
            "FROM alpine:${ALPINE_VERSION} AS openssl-build",
            "openssl-pqc.cnf",
            "mods-available/eap",
            "mods-enabled/eap",
            "logdir = /var/log/radius",
            "auth = yes",
            "auth_log",
            "updated = return",
            "radius-detail.log",
            "policy.d/macsec-dot1x",
            "macsec-dot1x",
            "sites-enabled/tls",
            "clients-radsec.conf",
        ):
            if fragment not in dockerfile:
                errors.append(f"Dockerfile must contain: {fragment!r}")

    return errors


def validate_topology(
    data: dict[str, Any],
    repo_root: Path | None = None,
    *,
    ceos_image: str | None = None,
    mgmt_subnet: str | None = None,
    mgmt_ipv6_subnet: str | None = None,
) -> list[str]:
    """Return a list of contract violations (empty when valid)."""
    errors: list[str] = []
    expected_ceos_image = ceos_image or DEFAULT_CEOS_IMAGE
    expected_mgmt_subnet = mgmt_subnet or DEFAULT_MGMT_SUBNET
    expected_mgmt_ipv6_subnet = mgmt_ipv6_subnet or DEFAULT_MGMT_IPV6_SUBNET
    expected_mgmt_ips = mgmt_ips_for_subnet(expected_mgmt_subnet)
    expected_mgmt_ipv6_ips = mgmt_ipv6_ips_for_subnet(expected_mgmt_ipv6_subnet)

    if data.get("name") != LAB_NAME:
        errors.append(f"name must be {LAB_NAME}")
    if data.get("prefix") != CLAB_PREFIX:
        errors.append(f"prefix must be {CLAB_PREFIX}")

    mgmt = data.get("mgmt", {})
    if mgmt.get("network") != MGMT_NETWORK:
        errors.append(f"mgmt.network must be {MGMT_NETWORK}")
    if mgmt.get("bridge") != MGMT_BRIDGE:
        errors.append(f"mgmt.bridge must be {MGMT_BRIDGE}")
    if mgmt.get("ipv4-subnet") != expected_mgmt_subnet:
        errors.append(f"mgmt.ipv4-subnet must be {expected_mgmt_subnet}")
    expected_gateway = mgmt_gateway(expected_mgmt_subnet)
    if mgmt.get("ipv4-gw") not in (expected_gateway, "${MGMT_GATEWAY}"):
        errors.append(f"mgmt.ipv4-gw must be {expected_gateway}")
    if mgmt.get("ipv6-subnet") not in (expected_mgmt_ipv6_subnet, MGMT_IPV6_SUBNET_PLACEHOLDER):
        errors.append(f"mgmt.ipv6-subnet must be {expected_mgmt_ipv6_subnet}")
    expected_ipv6_gateway = mgmt_ipv6_gateway(expected_mgmt_ipv6_subnet)
    if mgmt.get("ipv6-gw") not in (expected_ipv6_gateway, "${MGMT_IPV6_GATEWAY}"):
        errors.append(f"mgmt.ipv6-gw must be {expected_ipv6_gateway}")

    topology = data.get("topology", {})
    if MGMT_BRIDGE in topology.get("nodes", {}):
        errors.append(
            f"topology must not declare {MGMT_BRIDGE} node "
            f"(mgmt.bridge names the host bridge backing docker mgmt)"
        )
    kinds = topology.get("kinds", {}).get("arista_ceos", {})
    actual_ceos_image = kinds.get("image")
    if actual_ceos_image not in (expected_ceos_image, CEOS_IMAGE_PLACEHOLDER):
        errors.append(f"arista_ceos image must be {expected_ceos_image}")
    if kinds.get("env", {}).get("CLAB_MGMT_VRF") != MGMT_VRF_ENV:
        errors.append(f"CLAB_MGMT_VRF must be {MGMT_VRF_ENV}")

    nodes = topology.get("nodes", {})

    for node, expected_ip in expected_mgmt_ips.items():
        node_cfg = nodes.get(node)
        if node_cfg is None:
            errors.append(f"missing node {node}")
            continue
        if node_cfg.get("mgmt-ipv4") != expected_ip:
            errors.append(f"{node} mgmt-ipv4 must be {expected_ip}")
        expected_ipv6_ip = expected_mgmt_ipv6_ips[node]
        if node_cfg.get("mgmt-ipv6") != expected_ipv6_ip:
            errors.append(f"{node} mgmt-ipv6 must be {expected_ipv6_ip}")
        if node in CEOS_MGMT_NODES:
            if node_cfg.get("network-mode") == "none":
                errors.append(
                    f"{node} must use default docker mgmt (cEOS eth0 is reserved; "
                    f"do not set network-mode: none or wire eth0 in links)"
                )
        elif node in MGMT_LINUX_NODES:
            if node_cfg.get("network-mode") == "none":
                errors.append(f"{node} must use default docker mgmt (do not set network-mode: none)")

    for host in HOST_DATA_PLANE:
        host_cfg = nodes.get(host)
        if host_cfg is None:
            errors.append(f"missing node {host}")
            continue
        if host_cfg.get("network-mode") == "none":
            errors.append(f"{host} must use default docker mgmt (do not set network-mode: none)")

    radius_cfg = nodes.get("radius")
    if radius_cfg is None:
        errors.append("missing node radius")
    elif radius_cfg.get("image") != RADIUS_IMAGE:
        errors.append(f"radius image must be {RADIUS_IMAGE}")

    syslog_cfg = nodes.get("syslog")
    if syslog_cfg is None:
        errors.append("missing node syslog")
    else:
        if syslog_cfg.get("kind") != "linux":
            errors.append("syslog kind must be linux")
        if syslog_cfg.get("image") != SYSLOG_IMAGE:
            errors.append(f"syslog image must be {SYSLOG_IMAGE}")
        if syslog_cfg.get("mgmt-ipv4") != expected_mgmt_ips["syslog"]:
            errors.append(f"syslog mgmt-ipv4 must be {expected_mgmt_ips['syslog']}")
        syslog_binds = syslog_cfg.get("binds", [])
        for expected_bind in SYSLOG_BINDS:
            if expected_bind not in syslog_binds:
                errors.append(f"syslog must bind {expected_bind}")

    for ceos, expected in CEOS_STARTUP_CONFIGS.items():
        startup = nodes.get(ceos, {}).get("startup-config")
        if startup != expected:
            errors.append(f"{ceos} startup-config must be {expected}")

    radius_binds = nodes.get("radius", {}).get("binds", [])
    for expected_bind in RADIUS_BINDS:
        if expected_bind not in radius_binds:
            errors.append(f"radius must bind {expected_bind}")

    kme_a_cfg = nodes.get("kme-a")
    if kme_a_cfg is None:
        errors.append("missing node kme-a")
    else:
        if kme_a_cfg.get("kind") != "linux":
            errors.append("kme-a kind must be linux")
        if kme_a_cfg.get("image") != KME_IMAGE:
            errors.append(f"kme-a image must be {KME_IMAGE}")
        if kme_a_cfg.get("mgmt-ipv4") != expected_mgmt_ips["kme-a"]:
            errors.append(f"kme-a mgmt-ipv4 must be {expected_mgmt_ips['kme-a']}")
        kme_a_binds = kme_a_cfg.get("binds", [])
        for expected_bind in KME_BINDS:
            if expected_bind not in kme_a_binds:
                errors.append(f"kme-a must bind {expected_bind}")
        kme_a_env = kme_a_cfg.get("env", {})
        for key, value in kme_env_for_node(
            "kme-a",
            mgmt_ips=expected_mgmt_ips,
            mgmt_ipv6_ips=expected_mgmt_ipv6_ips,
        ).items():
            if str(kme_a_env.get(key)) != value:
                errors.append(f"kme-a env {key} must be {value!r}")
        cap_add = kme_a_cfg.get("cap-add") or kme_a_cfg.get("cap_add") or []
        if "NET_ADMIN" not in cap_add:
            errors.append("kme-a must include cap-add NET_ADMIN for mgmt-plane iptables isolation")

    kme_b_cfg = nodes.get("kme-b")
    if kme_b_cfg is None:
        errors.append("missing node kme-b")
    else:
        if kme_b_cfg.get("kind") != "linux":
            errors.append("kme-b kind must be linux")
        if kme_b_cfg.get("image") != KME_IMAGE:
            errors.append(f"kme-b image must be {KME_IMAGE}")
        if kme_b_cfg.get("mgmt-ipv4") != expected_mgmt_ips["kme-b"]:
            errors.append(f"kme-b mgmt-ipv4 must be {expected_mgmt_ips['kme-b']}")
        kme_b_binds = kme_b_cfg.get("binds", [])
        for expected_bind in KME_BINDS:
            if expected_bind not in kme_b_binds:
                errors.append(f"kme-b must bind {expected_bind}")
        kme_b_env = kme_b_cfg.get("env", {})
        for key, value in kme_env_for_node(
            "kme-b",
            mgmt_ips=expected_mgmt_ips,
            mgmt_ipv6_ips=expected_mgmt_ipv6_ips,
        ).items():
            if str(kme_b_env.get(key)) != value:
                errors.append(f"kme-b env {key} must be {value!r}")

        cap_add = kme_b_cfg.get("cap-add") or kme_b_cfg.get("cap_add") or []
        if "NET_ADMIN" not in cap_add:
            errors.append("kme-b must include cap-add NET_ADMIN for mgmt-plane iptables isolation")

    kme_data_plane_endpoints = {
        endpoint
        for link in topology.get("links", [])
        for endpoint in link.get("endpoints", [])
        if endpoint.startswith("kme-a:") or endpoint.startswith("kme-b:")
    } - {f"kme-a:eth0", f"kme-b:eth0"}
    if kme_data_plane_endpoints:
        errors.append(
            f"KME nodes must not have data-plane links (found {sorted(kme_data_plane_endpoints)})"
        )

    for ceos, expected_binds in CEOS_BINDS.items():
        actual_binds = nodes.get(ceos, {}).get("binds", [])
        for expected_bind in expected_binds:
            if expected_bind not in actual_binds:
                errors.append(f"{ceos} must bind {expected_bind}")
        expected_exec = CEOS_RADSEC_PKI_EXEC.get(ceos)
        if expected_exec is not None:
            exec_cmds = _host_exec_commands(nodes.get(ceos, {}))
            if expected_exec not in exec_cmds:
                errors.append(f"{ceos} must exec RadSec PKI install")

    actual_links = {
        tuple(link["endpoints"])
        for link in topology.get("links", [])
        if "endpoints" in link
    }
    for endpoints in LINKS:
        if endpoints not in actual_links and tuple(reversed(endpoints)) not in actual_links:
            errors.append(f"missing link {endpoints[0]} <-> {endpoints[1]}")
    for link in topology.get("links", []):
        for endpoint in link.get("endpoints", []):
            if endpoint.startswith(f"{MGMT_BRIDGE}:") or endpoint.endswith(":eth0"):
                if any(endpoint.startswith(f"{node}:") for node in MGMT_NODES):
                    errors.append(
                        f"mgmt connectivity must use docker mgmt, not topology link {endpoint!r}"
                    )

    errors.extend(validate_host_data_plane(nodes))
    errors.extend(validate_mgmt_topology_nodes(nodes))
    errors.extend(validate_ceos_configs(
        repo_root,
        mgmt_subnet=expected_mgmt_subnet,
        mgmt_ipv6_subnet=expected_mgmt_ipv6_subnet,
    ))
    errors.extend(validate_radius_configs(
        repo_root,
        mgmt_subnet=expected_mgmt_subnet,
        mgmt_ipv6_subnet=expected_mgmt_ipv6_subnet,
    ))
    errors.extend(validate_syslog_configs(repo_root))
    errors.extend(validate_topo_host_paths(repo_root))

    return errors
