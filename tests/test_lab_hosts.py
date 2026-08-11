from lab.test_lab import (
    format_host_connectivity_matrix,
    host_data_ips,
    host_ping_pairs,
)


def test_host_data_ips_match_contract() -> None:
    assert host_data_ips() == {
        "host1": "10.0.1.1",
        "host2": "10.0.2.1",
        "host3": "10.0.3.1",
    }


def test_host_ping_pairs_cover_all_off_diagonal() -> None:
    pairs = host_ping_pairs()
    assert len(pairs) == 6
    assert ("host1", "host2", "10.0.2.1") in pairs
    assert ("host2", "host1", "10.0.1.1") in pairs
    assert ("host3", "host2", "10.0.2.1") in pairs
    assert all(src != dst for src, dst, _ in pairs)


def test_format_host_connectivity_matrix_all_ok() -> None:
    results = {
        ("host1", "host2"): True,
        ("host1", "host3"): True,
        ("host2", "host1"): True,
        ("host2", "host3"): True,
        ("host3", "host1"): True,
        ("host3", "host2"): True,
    }
    matrix = format_host_connectivity_matrix(results)
    assert "HOST ROUTING (data-plane ping matrix)" in matrix
    assert "host1" in matrix
    assert "10.0.1.1" in matrix
    assert "host1 →" in matrix
    assert matrix.count("OK") == 6
    assert matrix.count("—") == 3
    assert "FAIL" not in matrix


def test_format_host_connectivity_matrix_shows_failures() -> None:
    results = {
        ("host1", "host2"): True,
        ("host1", "host3"): False,
        ("host2", "host1"): True,
        ("host2", "host3"): True,
        ("host3", "host1"): True,
        ("host3", "host2"): False,
    }
    matrix = format_host_connectivity_matrix(results)
    assert matrix.count("FAIL") == 2
    assert matrix.count("OK") == 4
