from lab.report import ICON_FAIL, ICON_OK
from lab.test_hosts import (
    format_host_connectivity_matrix,
    host_data_ips,
    host_data_ips6,
    host_ping_groups,
)
from lab.topology_contract import IP_FAMILY_IPV4, IP_FAMILY_IPV6


def test_host_data_ips_match_contract() -> None:
    assert host_data_ips() == {
        "host1": "10.0.1.1",
        "host2": "10.0.2.1",
        "host3": "10.0.3.1",
    }


def test_host_data_ips6_match_contract() -> None:
    assert host_data_ips6() == {
        "host1": "2001:db8:1::1",
        "host2": "2001:db8:2::1",
        "host3": "2001:db8:3::1",
    }


def test_host_ping_groups_cover_all_off_diagonal() -> None:
    groups = host_ping_groups()
    assert len(groups) == 6
    host1_host2 = next(group for group in groups if group[0] == "host1" and group[1] == "host2")
    targets = dict(host1_host2[2])
    assert targets[IP_FAMILY_IPV4] == "10.0.2.1"
    assert targets[IP_FAMILY_IPV6] == "2001:db8:2::1"
    assert all(src != dst for src, dst, _ in groups)


def test_format_host_connectivity_matrix_all_ok() -> None:
    results_v4 = {
        ("host1", "host2"): True,
        ("host1", "host3"): True,
        ("host2", "host1"): True,
        ("host2", "host3"): True,
        ("host3", "host1"): True,
        ("host3", "host2"): True,
    }
    results_v6 = dict(results_v4)
    matrix = format_host_connectivity_matrix(results_v4, results_v6)
    assert "HOST ROUTING (data-plane ping matrix)" in matrix
    assert "host1" in matrix
    assert "10.0.1.1" in matrix
    assert "2001:db8:1::1" in matrix
    assert "2001:db8:2::1" in matrix
    assert "host1 →" in matrix
    assert matrix.count(ICON_OK) == 12
    assert ICON_FAIL not in matrix


def test_format_host_connectivity_matrix_shows_failures() -> None:
    results_v4 = {
        ("host1", "host2"): True,
        ("host1", "host3"): False,
        ("host2", "host1"): True,
        ("host2", "host3"): True,
        ("host3", "host1"): True,
        ("host3", "host2"): False,
    }
    results_v6 = dict(results_v4)
    matrix = format_host_connectivity_matrix(results_v4, results_v6)
    assert matrix.count(ICON_FAIL) == 4
    assert matrix.count(ICON_OK) == 8
