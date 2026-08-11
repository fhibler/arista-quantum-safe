"""Dual-stack contract tests (IPv4 and IPv6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from lab.render_topo import render_lab
from lab.topology_contract import (
    CEOS_DATA_PLANE,
    DEFAULT_MGMT_IPV6_SUBNET,
    DEFAULT_MGMT_SUBNET,
    FAMILY_LABELS,
    GEN_TOPOLOGY_PATH,
    HOST_DATA_PLANE,
    IP_FAMILY_IPV4,
    IP_FAMILY_IPV6,
    MGMT_HOST_SUFFIXES,
    MGMT_IPV6_IPS,
    MGMT_IPS,
    RADIUS_SERVER_IPV6,
    SYSLOG_SERVER_IPV4,
    SYSLOG_SERVER_IPV6,
    family_label,
    load_topology,
    mgmt_ips_for_family,
    mgmt_node_ip,
    validate_ceos_configs,
    validate_radius_configs,
    validate_topology,
)
from lab.syslog_checks import expected_syslog_host_line


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def rendered_configs(repo_root: Path) -> None:
    render_lab(repo_root=repo_root)


@pytest.fixture
def generated_topology(repo_root: Path) -> dict:
    render_lab(repo_root=repo_root)
    return load_topology(GEN_TOPOLOGY_PATH)


def test_mgmt_ips_parallel_suffixes(ip_family: str) -> None:
    for node, suffix in MGMT_HOST_SUFFIXES.items():
        ip = mgmt_node_ip(node, ip_family)
        if ip_family == IP_FAMILY_IPV4:
            assert ip.endswith(f".{suffix}")
        else:
            assert ip.endswith(f"::{suffix}")


@pytest.mark.parametrize("node", sorted(MGMT_IPS))
def test_mgmt_node_has_expected_address(ip_family: str, node: str) -> None:
    if ip_family == IP_FAMILY_IPV4:
        assert mgmt_node_ip(node, ip_family) == MGMT_IPS[node]
    else:
        assert mgmt_node_ip(node, ip_family) == MGMT_IPV6_IPS[node]


def test_radius_ipv6_and_syslog_dual_stack_endpoints(repo_root: Path) -> None:
    text = (repo_root / "lab" / ".gen" / "ceos1-both.cfg").read_text(encoding="utf-8")
    assert RADIUS_SERVER_IPV6 in text
    assert expected_syslog_host_line(SYSLOG_SERVER_IPV4) in text
    assert expected_syslog_host_line(SYSLOG_SERVER_IPV6) in text
    assert f"radius-server host {MGMT_IPS['radius']} " not in text


def test_ceos_configs_valid_for_both_families(repo_root: Path, ip_family: str) -> None:
    errors = validate_ceos_configs(
        repo_root,
        mgmt_subnet=DEFAULT_MGMT_SUBNET,
        mgmt_ipv6_subnet=DEFAULT_MGMT_IPV6_SUBNET,
    )
    assert errors == [], f"{ip_family}: " + "\n".join(errors)


def test_radius_configs_valid_for_both_families(repo_root: Path, ip_family: str) -> None:
    errors = validate_radius_configs(
        repo_root,
        mgmt_subnet=DEFAULT_MGMT_SUBNET,
        mgmt_ipv6_subnet=DEFAULT_MGMT_IPV6_SUBNET,
    )
    assert errors == [], f"{ip_family}: " + "\n".join(errors)


@pytest.mark.parametrize("ceos", sorted(CEOS_DATA_PLANE))
def test_ceos_data_plane_addresses(ip_family: str, ceos: str) -> None:
    spec = CEOS_DATA_PLANE[ceos]
    if ip_family == IP_FAMILY_IPV4:
        assert spec["eth1"].startswith("10.")
        assert spec["eth8"].startswith("10.")
    else:
        assert spec["eth1_ipv6"].startswith("2001:db8:")
        assert spec["eth8_ipv6"].startswith("2001:db8:")


@pytest.mark.parametrize("host", sorted(HOST_DATA_PLANE))
def test_host_data_plane_addresses(ip_family: str, host: str) -> None:
    spec = HOST_DATA_PLANE[host]
    if ip_family == IP_FAMILY_IPV4:
        assert spec["addr"].startswith("10.")
        assert spec["gateway"].startswith("10.")
    else:
        assert spec["addr6"].startswith("2001:db8:")
        assert spec["gateway6"].startswith("2001:db8:")


def test_generated_topology_dual_stack_mgmt(generated_topology: dict, ip_family: str) -> None:
    expected = mgmt_ips_for_family(ip_family)
    nodes = generated_topology["topology"]["nodes"]
    key = "mgmt-ipv4" if ip_family == IP_FAMILY_IPV4 else "mgmt-ipv6"
    for node, addr in expected.items():
        assert nodes[node][key] == addr


def test_validate_topology_dual_stack(repo_root: Path, ip_family: str) -> None:
    data = load_topology(GEN_TOPOLOGY_PATH)
    errors = validate_topology(
        data,
        repo_root=repo_root,
        mgmt_subnet=DEFAULT_MGMT_SUBNET,
        mgmt_ipv6_subnet=DEFAULT_MGMT_IPV6_SUBNET,
    )
    assert errors == [], f"{ip_family}: " + "\n".join(errors)


def test_family_label() -> None:
    assert family_label(IP_FAMILY_IPV4) == "IPv4"
    assert family_label(IP_FAMILY_IPV6) == "IPv6"
    assert FAMILY_LABELS[IP_FAMILY_IPV4] == "IPv4"
