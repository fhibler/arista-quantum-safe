"""Topology and configuration contract validation for the qkd-macsec-radius lab."""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
TOPOLOGY_PATH = REPO_ROOT / "lab" / "qkd-macsec-radius.clab.yml"
GEN_TOPOLOGY_PATH = REPO_ROOT / "lab" / ".gen.qkd-macsec-radius.clab.yml"
GEN_CONFIG_DIR = REPO_ROOT / "lab" / ".gen"

DEFAULT_MGMT_SUBNET = "172.20.127.0/24"
MGMT_HOST_SUFFIXES = {
    "ceos1": 11,
    "ceos2": 12,
    "host1": 21,
    "host2": 22,
    "radius": 50,
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


MGMT_SUBNET = DEFAULT_MGMT_SUBNET
MGMT_IPS = mgmt_ips_for_subnet(DEFAULT_MGMT_SUBNET)

LINKS = [
    ("ceos1:eth1", "ceos2:eth1"),
    ("ceos1:eth2", "host1:eth1"),
    ("ceos2:eth2", "host2:eth1"),
]

DEFAULT_CEOS_IMAGE = "ceos:4.36.1F"
CEOS_IMAGE_PLACEHOLDER = "${CEOS_IMAGE}"
MGMT_SUBNET_PLACEHOLDER = "${MGMT_SUBNET}"
MGMT_VRF_ENV = "MGMT"
MGMT_VRF_ENV = "MGMT"
RADSEC_SECRET = "radsec"
RADSEC_PORT = 2083
SSL_PROFILE = "RADSEC"
EAPI_SSL_PROFILE = "EAPI"
SSH_PQC_KEX = "mlkem768x25519-sha256"
SSH_PQC_CIPHERS = (
    "aes256-gcm@openssh.com aes128-gcm@openssh.com chacha20-poly1305@openssh.com"
)
SSH_PQC_MACS = "hmac-sha2-256 hmac-sha2-512"
RADIUS_SERVER_IP = MGMT_IPS["radius"]

HOST_DATA_PLANE = {
    "host1": {
        "addr": "10.0.1.1/24",
        "gateway": "10.0.1.254",
    },
    "host2": {
        "addr": "10.0.2.1/24",
        "gateway": "10.0.2.254",
    },
}

def ceos_data_plane(subnet: str | None = None) -> dict[str, dict[str, Any]]:
    """Return locked cEOS data-plane expectations for the given mgmt subnet."""
    ips = mgmt_ips_for_subnet(subnet)
    prefix = mgmt_prefix_len(subnet)
    return {
        "ceos1": {
            "mgmt_ip": f"{ips['ceos1']}/{prefix}",
            "mgmt_gateway": mgmt_gateway(subnet),
            "eth1": "10.255.0.1/30",
            "eth2": "10.0.1.254/24",
            "static_route": ("10.0.2.0/24", "10.255.0.2"),
        },
        "ceos2": {
            "mgmt_ip": f"{ips['ceos2']}/{prefix}",
            "mgmt_gateway": mgmt_gateway(subnet),
            "eth1": "10.255.0.2/30",
            "eth2": "10.0.2.254/24",
            "static_route": ("10.0.1.0/24", "10.255.0.1"),
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
    "logs/radius:/var/log/radius",
]

CEOS_RADSEC_PKI_EXEC = {
    "ceos1": (
        'bash -c \'{ echo enable; echo "copy flash:radsec-ca.pem certificate:"; '
        'echo "copy flash:ceos1-client.pem certificate:"; '
        'echo "copy flash:ceos1-client.key sslkey:"; '
        'echo "copy flash:ceos1-eapi.pem certificate:"; '
        'echo "copy flash:ceos1-eapi.key sslkey:"; } | Cli\''
    ),
    "ceos2": (
        'bash -c \'{ echo enable; echo "copy flash:radsec-ca.pem certificate:"; '
        'echo "copy flash:ceos2-client.pem certificate:"; '
        'echo "copy flash:ceos2-client.key sslkey:"; '
        'echo "copy flash:ceos2-eapi.pem certificate:"; '
        'echo "copy flash:ceos2-eapi.key sslkey:"; } | Cli\''
    ),
}

CEOS_BINDS = {
    "ceos1": [
        "../lab/.gen/pki/radsec-ca.pem:/mnt/flash/radsec-ca.pem:ro",
        "../lab/.gen/pki/ceos1-client.pem:/mnt/flash/ceos1-client.pem:ro",
        "../lab/.gen/pki/ceos1-client.key:/mnt/flash/ceos1-client.key:ro",
        "../lab/.gen/pki/ceos1-eapi.pem:/mnt/flash/ceos1-eapi.pem:ro",
        "../lab/.gen/pki/ceos1-eapi.key:/mnt/flash/ceos1-eapi.key:ro",
    ],
    "ceos2": [
        "../lab/.gen/pki/radsec-ca.pem:/mnt/flash/radsec-ca.pem:ro",
        "../lab/.gen/pki/ceos2-client.pem:/mnt/flash/ceos2-client.pem:ro",
        "../lab/.gen/pki/ceos2-client.key:/mnt/flash/ceos2-client.key:ro",
        "../lab/.gen/pki/ceos2-eapi.pem:/mnt/flash/ceos2-eapi.pem:ro",
        "../lab/.gen/pki/ceos2-eapi.key:/mnt/flash/ceos2-eapi.key:ro",
    ],
}

PKI_FILES = [
    "ca.pem",
    "radsec-ca.pem",
    "server.pem",
    "ceos1-client.pem",
    "ceos1-client.key",
    "ceos1-eapi.pem",
    "ceos1-eapi.key",
    "ceos2-client.pem",
    "ceos2-client.key",
    "ceos2-eapi.pem",
    "ceos2-eapi.key",
]

CEOS_STARTUP_CONFIGS = {
    "ceos1": "../lab/.gen/ceos1.cfg",
    "ceos2": "../lab/.gen/ceos2.cfg",
}

CONFIG_PATHS = {
    "ceos1": REPO_ROOT / "configs" / "ceos" / "ceos1.cfg.in",
    "ceos2": REPO_ROOT / "configs" / "ceos" / "ceos2.cfg.in",
    "clients": REPO_ROOT / "configs" / "radius" / "raddb" / "clients.conf.in",
    "clients_radsec": REPO_ROOT / "configs" / "radius" / "raddb" / "clients-radsec.conf.in",
    "tls_site": REPO_ROOT / "configs" / "radius" / "raddb" / "sites-available" / "tls",
    "radiusd": REPO_ROOT / "configs" / "radius" / "raddb" / "radiusd.conf",
    "dockerfile": REPO_ROOT / "docker" / "radius" / "Dockerfile",
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
) -> list[str]:
    """Validate rendered cEOS startup configs against mgmt and data-plane contract."""
    errors: list[str] = []
    root = repo_root or REPO_ROOT
    expected_plane = ceos_data_plane(mgmt_subnet)
    radius_ip = mgmt_ips_for_subnet(mgmt_subnet)["radius"]

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
        if f"ip address {expected['eth1']}" not in text:
            errors.append(f"{ceos}.cfg Ethernet1 must have {expected['eth1']}")
        if f"ip address {expected['eth2']}" not in text:
            errors.append(f"{ceos}.cfg Ethernet2 must have {expected['eth2']}")

        prefix, nexthop = expected["static_route"]
        if f"ip route {prefix} {nexthop}" not in text:
            errors.append(f"{ceos}.cfg must route {prefix} via {nexthop}")

        if f"radius-server host {radius_ip} vrf MGMT tls ssl-profile {SSL_PROFILE}" not in text:
            errors.append(f"{ceos}.cfg must configure RadSec server in MGMT VRF")
        if "ssl profile RADSEC" not in text:
            errors.append(f"{ceos}.cfg must define ssl profile RADSEC")
        if "tls versions 1.3" not in text:
            errors.append(f"{ceos}.cfg must restrict ssl profile to TLS 1.3")
        if "key-establishment-group X25519MLKEM768:ecdh_x25519:secp256r1" not in text:
            errors.append(f"{ceos}.cfg must configure PQC-hybrid key establishment groups")
        if f"server {radius_ip} tls vrf MGMT" not in text:
            errors.append(f"{ceos}.cfg aaa group must use RadSec transport in MGMT VRF")
        if f"ssl profile {EAPI_SSL_PROFILE}" not in text:
            errors.append(f"{ceos}.cfg must define ssl profile {EAPI_SSL_PROFILE}")
        if f"protocol https ssl profile {EAPI_SSL_PROFILE}" not in text:
            errors.append(f"{ceos}.cfg must enable eAPI HTTPS with ssl profile {EAPI_SSL_PROFILE}")
        if f"certificate {ceos}-eapi.pem key {ceos}-eapi.key" not in text:
            errors.append(f"{ceos}.cfg must reference per-switch eAPI certificate")
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

    return errors


def validate_radius_configs(
    repo_root: Path | None = None,
    *,
    mgmt_subnet: str | None = None,
) -> list[str]:
    """Validate FreeRADIUS client and logging configuration."""
    errors: list[str] = []
    root = repo_root or REPO_ROOT
    mgmt_ips = mgmt_ips_for_subnet(mgmt_subnet)

    clients_path = root / "lab" / ".gen" / "clients.conf"
    clients_radsec_path = root / "lab" / ".gen" / "clients-radsec.conf"
    tls_site_path = root / "configs" / "radius" / "raddb" / "sites-available" / "tls"
    radiusd_path = root / "configs" / "radius" / "raddb" / "radiusd.conf"
    dockerfile_path = root / "docker" / "radius" / "Dockerfile"

    if not clients_radsec_path.is_file():
        errors.append("missing lab/.gen/clients-radsec.conf (run make gen-topo)")
    else:
        clients_radsec = clients_radsec_path.read_text(encoding="utf-8")
        for ceos, ip in (("ceos1", mgmt_ips["ceos1"]), ("ceos2", mgmt_ips["ceos2"])):
            block = re.search(rf"client\s+{ceos}\s*\{{([^}}]+)\}}", clients_radsec, re.DOTALL)
            if block is None:
                errors.append(f"clients-radsec.conf must define client {ceos}")
                continue
            body = block.group(1)
            if f"ipaddr  = {ip}" not in body and f"ipaddr = {ip}" not in body:
                errors.append(f"clients-radsec.conf {ceos} ipaddr must be {ip}")
            if "proto   = tls" not in body and "proto = tls" not in body:
                errors.append(f"clients-radsec.conf {ceos} must use proto tls")
            if f"secret  = {RADSEC_SECRET}" not in body and f"secret = {RADSEC_SECRET}" not in body:
                errors.append(f"clients-radsec.conf {ceos} secret must be {RADSEC_SECRET}")
            if "require_message_authenticator = true" not in body:
                errors.append(f"clients-radsec.conf {ceos} must set require_message_authenticator")
            if "limit_proxy_state = true" not in body:
                errors.append(f"clients-radsec.conf {ceos} must set limit_proxy_state")

    if not tls_site_path.is_file():
        errors.append("missing configs/radius/raddb/sites-available/tls")
    else:
        tls_site = tls_site_path.read_text(encoding="utf-8")
        if 'tls_min_version = "1.3"' not in tls_site:
            errors.append("tls site must set tls_min_version 1.3")
        if f"port = {RADSEC_PORT}" not in tls_site:
            errors.append(f"tls site must listen on port {RADSEC_PORT}")
        if "require_client_cert = yes" not in tls_site:
            errors.append("tls site must require client certificates")

    if not clients_path.is_file():
        errors.append("missing lab/.gen/clients.conf (run make gen-topo)")
    else:
        clients = clients_path.read_text(encoding="utf-8")
        if "172.17.0.0/16" not in clients:
            errors.append("clients.conf must include dockernet client 172.17.0.0/16")
        if "client ceos1" in clients or "client ceos2" in clients:
            errors.append("clients.conf must not define plain UDP ceos clients (use clients-radsec.conf)")

    if not radiusd_path.is_file():
        errors.append("missing configs/radius/raddb/radiusd.conf")
    else:
        radiusd = radiusd_path.read_text(encoding="utf-8")
        if "/var/log/radius/radius.log" not in radiusd:
            errors.append("radiusd.conf must log to /var/log/radius/radius.log")

    if not dockerfile_path.is_file():
        errors.append("missing docker/radius/Dockerfile")
    else:
        dockerfile = dockerfile_path.read_text(encoding="utf-8")
        for fragment in (
            "ARG FREERADIUS_VERSION=release_3_2_6",
            "ARG OPENSSL_VERSION=openssl-3.5.7",
            "FROM alpine:${ALPINE_VERSION} AS openssl-build",
            "openssl-pqc.cnf",
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
) -> list[str]:
    """Return a list of contract violations (empty when valid)."""
    errors: list[str] = []
    expected_ceos_image = ceos_image or DEFAULT_CEOS_IMAGE
    expected_mgmt_subnet = mgmt_subnet or DEFAULT_MGMT_SUBNET
    expected_mgmt_ips = mgmt_ips_for_subnet(expected_mgmt_subnet)

    if data.get("name") != "qkd-macsec-radius":
        errors.append("name must be qkd-macsec-radius")

    mgmt = data.get("mgmt", {})
    if mgmt.get("ipv4-subnet") != expected_mgmt_subnet:
        errors.append(f"mgmt.ipv4-subnet must be {expected_mgmt_subnet}")

    topology = data.get("topology", {})
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

    for ceos, expected in CEOS_STARTUP_CONFIGS.items():
        startup = nodes.get(ceos, {}).get("startup-config")
        if startup != expected:
            errors.append(f"{ceos} startup-config must be {expected}")

    radius_binds = nodes.get("radius", {}).get("binds", [])
    for expected_bind in RADIUS_BINDS:
        if expected_bind not in radius_binds:
            errors.append(f"radius must bind {expected_bind}")

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

    errors.extend(validate_host_data_plane(nodes))
    errors.extend(validate_ceos_configs(repo_root, mgmt_subnet=expected_mgmt_subnet))
    errors.extend(validate_radius_configs(repo_root, mgmt_subnet=expected_mgmt_subnet))
    errors.extend(validate_topo_host_paths(repo_root))

    return errors
