"""Unit tests for syslog check helpers."""

from __future__ import annotations

from lab.syslog_checks import (
    PQC_GROUP,
    check_switch_syslog_ssl_profile_detail,
    cleartext_capture_filter,
    cleartext_syslog_lines,
    expected_syslog_host_line,
    negotiated_pqc_group,
)
from lab.topology_contract import SYSLOG_PORT, SYSLOG_SSL_PROFILE, SYSLOG_SERVER_IPV6


def test_cleartext_capture_filter_uses_src_host() -> None:
    filt = cleartext_capture_filter("172.20.127.11")
    assert filt.startswith("src host 172.20.127.11")
    assert "udp port 514" in filt


def test_negotiated_pqc_group() -> None:
    assert negotiated_pqc_group(f"Negotiated group: {PQC_GROUP}")
    assert not negotiated_pqc_group("Negotiated group: ecdh_x25519")


def test_syslog_contract_constants() -> None:
    assert SYSLOG_SSL_PROFILE == "SYSLOG"
    assert SYSLOG_PORT == 6514


def test_cleartext_syslog_lines_detects_udp() -> None:
    cfg = "logging vrf MGMT host 10.0.0.1 514 protocol udp"
    assert cleartext_syslog_lines(cfg) == [cfg]


def test_cleartext_syslog_lines_detects_plain_tcp() -> None:
    cfg = "logging vrf MGMT host 10.0.0.1 514 protocol tcp"
    assert cleartext_syslog_lines(cfg) == [cfg]


def test_cleartext_syslog_lines_allows_tls(ip_family: str) -> None:
    syslog_ip = SYSLOG_SERVER_IPV6 if ip_family == "ipv6" else "172.20.127.53"
    cfg = expected_syslog_host_line(syslog_ip)
    assert cleartext_syslog_lines(cfg) == []


def test_cleartext_syslog_lines_detects_host_without_protocol() -> None:
    cfg = "logging host 10.0.0.1"
    assert cleartext_syslog_lines(cfg) == [cfg]


def test_expected_syslog_host_line(ip_family: str) -> None:
    syslog_ip = SYSLOG_SERVER_IPV6 if ip_family == "ipv6" else "172.20.127.53"
    line = expected_syslog_host_line(syslog_ip)
    assert "protocol tls ssl-profile SYSLOG" in line
    assert str(SYSLOG_PORT) in line
    assert syslog_ip in line


def test_syslog_ssl_profile_detail_accepts_eos_json() -> None:
    detail = {
        "profileStatus": {
            "SYSLOG": {
                "profileState": "valid",
                "keyEstablishmentGroups": "X25519MLKEM768",
            }
        }
    }
    check_switch_syslog_ssl_profile_detail(detail, node="ceos1-both")


def test_syslog_ssl_profile_detail_accepts_plain_text() -> None:
    detail = "Profile: SYSLOG\nState: valid\nTLS key establishment group(v1.3): X25519MLKEM768\n"
    check_switch_syslog_ssl_profile_detail(detail, node="ceos1-both")


def test_syslog_ssl_profile_detail_rejects_invalid_json_state() -> None:
    detail = {"profileStatus": {"SYSLOG": {"profileState": "invalid"}}}
    try:
        check_switch_syslog_ssl_profile_detail(detail, node="ceos1-both")
    except Exception as exc:
        assert "must be valid" in str(exc)
    else:
        raise AssertionError("expected SyslogCheckError")
