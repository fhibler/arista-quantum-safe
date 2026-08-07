"""Topology and configuration contract validation for the qkd-macsec-radius lab."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
TOPOLOGY_PATH = REPO_ROOT / "lab" / "qkd-macsec-radius.clab.yml"
GEN_TOPOLOGY_PATH = REPO_ROOT / "lab" / ".gen.qkd-macsec-radius.clab.yml"

MGMT_IPS = {
    "ceos1": "192.168.127.11",
    "ceos2": "192.168.127.12",
    "host1": "192.168.127.21",
    "host2": "192.168.127.22",
    "radius": "192.168.127.50",
}

LINKS = [
    ("ceos1:eth1", "ceos2:eth1"),
    ("ceos1:eth2", "host1:eth1"),
    ("ceos2:eth2", "host2:eth1"),
]

DEFAULT_CEOS_IMAGE = "ceos:4.36.1F"
CEOS_IMAGE_PLACEHOLDER = "${CEOS_IMAGE}"
MGMT_SUBNET = "192.168.127.0/24"
MGMT_VRF_ENV = "MGMT"
RADIUS_SECRET = "testing123"
RADIUS_SERVER_IP = "192.168.127.50"

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

CEOS_DATA_PLANE = {
    "ceos1": {
        "mgmt_ip": "192.168.127.11/24",
        "eth1": "10.255.0.1/30",
        "eth2": "10.0.1.254/24",
        "static_route": ("10.0.2.0/24", "10.255.0.2"),
    },
    "ceos2": {
        "mgmt_ip": "192.168.127.12/24",
        "eth1": "10.255.0.2/30",
        "eth2": "10.0.2.254/24",
        "static_route": ("10.0.1.0/24", "10.255.0.1"),
    },
}

RADIUS_BINDS = [
    "configs/radius/raddb/clients.conf:/etc/raddb/clients.conf:ro",
    "configs/radius/raddb/radiusd.conf:/etc/raddb/radiusd-log.conf:ro",
    "lab/logs/radius:/var/log/radius",
]

CONFIG_PATHS = {
    "ceos1": REPO_ROOT / "configs" / "ceos" / "ceos1.cfg",
    "ceos2": REPO_ROOT / "configs" / "ceos" / "ceos2.cfg",
    "clients": REPO_ROOT / "configs" / "radius" / "raddb" / "clients.conf",
    "radiusd": REPO_ROOT / "configs" / "radius" / "raddb" / "radiusd.conf",
    "dockerfile": REPO_ROOT / "docker" / "radius" / "Dockerfile",
}


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
        if f"ip route add default via {expected['gateway']} dev eth1" not in exec_text:
            errors.append(f"{host} exec must use default gateway {expected['gateway']}")

    return errors


def _ceos_config_text(name: str, repo_root: Path | None = None) -> str:
    root = repo_root or REPO_ROOT
    path = root / "configs" / "ceos" / f"{name}.cfg"
    if not path.is_file():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8")


def validate_ceos_configs(repo_root: Path | None = None) -> list[str]:
    """Validate cEOS startup configs against mgmt and data-plane contract."""
    errors: list[str] = []
    root = repo_root or REPO_ROOT

    for ceos, expected in CEOS_DATA_PLANE.items():
        path = root / "configs" / "ceos" / f"{ceos}.cfg"
        if not path.is_file():
            errors.append(f"missing {path.relative_to(root)}")
            continue

        text = path.read_text(encoding="utf-8")
        if "vrf instance MGMT" not in text:
            errors.append(f"{ceos}.cfg must define vrf instance MGMT")
        if f"ip address {expected['mgmt_ip']}" not in text:
            errors.append(f"{ceos}.cfg Management0 must have {expected['mgmt_ip']}")
        if f"ip address {expected['eth1']}" not in text:
            errors.append(f"{ceos}.cfg Ethernet1 must have {expected['eth1']}")
        if f"ip address {expected['eth2']}" not in text:
            errors.append(f"{ceos}.cfg Ethernet2 must have {expected['eth2']}")

        prefix, nexthop = expected["static_route"]
        if f"ip route {prefix} {nexthop}" not in text:
            errors.append(f"{ceos}.cfg must route {prefix} via {nexthop}")

        if f"radius-server host {RADIUS_SERVER_IP} vrf MGMT key {RADIUS_SECRET}" not in text:
            errors.append(f"{ceos}.cfg must configure RADIUS server in MGMT VRF")
        if "aaa group server radius RADIUS" not in text:
            errors.append(f"{ceos}.cfg must define aaa group server radius RADIUS")

    return errors


def validate_radius_configs(repo_root: Path | None = None) -> list[str]:
    """Validate FreeRADIUS client and logging configuration."""
    errors: list[str] = []
    root = repo_root or REPO_ROOT

    clients_path = root / "configs" / "radius" / "raddb" / "clients.conf"
    radiusd_path = root / "configs" / "radius" / "raddb" / "radiusd.conf"
    dockerfile_path = root / "docker" / "radius" / "Dockerfile"

    if not clients_path.is_file():
        errors.append("missing configs/radius/raddb/clients.conf")
    else:
        clients = clients_path.read_text(encoding="utf-8")
        for ceos, ip in (("ceos1", MGMT_IPS["ceos1"]), ("ceos2", MGMT_IPS["ceos2"])):
            block = re.search(rf"client\s+{ceos}\s*\{{([^}}]+)\}}", clients, re.DOTALL)
            if block is None:
                errors.append(f"clients.conf must define client {ceos}")
                continue
            body = block.group(1)
            if f"ipaddr  = {ip}" not in body and f"ipaddr = {ip}" not in body:
                errors.append(f"clients.conf {ceos} ipaddr must be {ip}")
            if f"secret  = {RADIUS_SECRET}" not in body and f"secret = {RADIUS_SECRET}" not in body:
                errors.append(f"clients.conf {ceos} secret must be {RADIUS_SECRET}")

        if "172.17.0.0/16" not in clients:
            errors.append("clients.conf must include dockernet client 172.17.0.0/16")

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
            "FROM alpine:3.20 AS radius-arm64",
            "FROM freeradius/freeradius-server:latest-3.2-alpine AS radius-amd64",
            "FROM radius-${TARGETARCH}",
        ):
            if fragment not in dockerfile:
                errors.append(f"Dockerfile must contain: {fragment!r}")

    return errors


def validate_topology(
    data: dict[str, Any],
    repo_root: Path | None = None,
    *,
    ceos_image: str | None = None,
) -> list[str]:
    """Return a list of contract violations (empty when valid)."""
    errors: list[str] = []
    expected_ceos_image = ceos_image or DEFAULT_CEOS_IMAGE

    if data.get("name") != "qkd-macsec-radius":
        errors.append("name must be qkd-macsec-radius")

    mgmt = data.get("mgmt", {})
    if mgmt.get("ipv4-subnet") != MGMT_SUBNET:
        errors.append(f"mgmt.ipv4-subnet must be {MGMT_SUBNET}")

    topology = data.get("topology", {})
    kinds = topology.get("kinds", {}).get("arista_ceos", {})
    actual_ceos_image = kinds.get("image")
    if actual_ceos_image not in (expected_ceos_image, CEOS_IMAGE_PLACEHOLDER):
        errors.append(f"arista_ceos image must be {expected_ceos_image}")
    if kinds.get("env", {}).get("CLAB_MGMT_VRF") != MGMT_VRF_ENV:
        errors.append(f"CLAB_MGMT_VRF must be {MGMT_VRF_ENV}")

    nodes = topology.get("nodes", {})
    for node, expected_ip in MGMT_IPS.items():
        node_cfg = nodes.get(node)
        if node_cfg is None:
            errors.append(f"missing node {node}")
            continue
        if node_cfg.get("mgmt-ipv4") != expected_ip:
            errors.append(f"{node} mgmt-ipv4 must be {expected_ip}")

    for ceos in ("ceos1", "ceos2"):
        startup = nodes.get(ceos, {}).get("startup-config")
        expected = f"configs/ceos/{ceos}.cfg"
        if startup != expected:
            errors.append(f"{ceos} startup-config must be {expected}")

    radius_binds = nodes.get("radius", {}).get("binds", [])
    for expected_bind in RADIUS_BINDS:
        if expected_bind not in radius_binds:
            errors.append(f"radius must bind {expected_bind}")

    actual_links = {
        tuple(link["endpoints"])
        for link in topology.get("links", [])
        if "endpoints" in link
    }
    for endpoints in LINKS:
        if endpoints not in actual_links and tuple(reversed(endpoints)) not in actual_links:
            errors.append(f"missing link {endpoints[0]} <-> {endpoints[1]}")

    errors.extend(validate_host_data_plane(nodes))
    errors.extend(validate_ceos_configs(repo_root))
    errors.extend(validate_radius_configs(repo_root))

    return errors
