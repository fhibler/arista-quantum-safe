"""Unit tests for syslog check helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from lab.syslog_checks import (
    PQC_GROUP,
    SyslogCheckError,
    TLS_KEY_SHARE_X25519,
    TLS_KEY_SHARE_X25519MLKEM768,
    _tcpdump_argv,
    _tcpdump_permission_denied,
    check_switch_syslog_logging_config,
    check_switch_syslog_ssl_profile_detail,
    cleartext_capture_filter,
    cleartext_syslog_lines,
    expected_syslog_host_line,
    expected_syslog_host_lines,
    is_pqc_hybrid_key_share_group,
    negotiated_pqc_group,
    tcpdump_captured_packet,
    tls_handshake_incomplete,
    tls_key_share_group_name,
    tshark_client_hello_filter,
)
from lab.topology_contract import (
    SYSLOG_PORT,
    SYSLOG_SSL_PROFILE,
    SYSLOG_SERVER_IPV4,
    SYSLOG_SERVER_IPV6,
    SYSLOG_TLS_PQC_SAFE_EOS_GROUPS,
    SYSLOG_TLS_PQC_SAFE_OPENSSL_GROUPS,
)


def test_cleartext_capture_filter_uses_src_host() -> None:
    filt = cleartext_capture_filter("172.20.127.11")
    assert filt.startswith("src host 172.20.127.11")
    assert "udp port 514" in filt


def test_negotiated_pqc_group() -> None:
    assert negotiated_pqc_group(f"Negotiated group: {PQC_GROUP}")
    assert not negotiated_pqc_group("Negotiated group: ecdh_x25519")


def test_tls_handshake_incomplete_detects_eof() -> None:
    output = "CONNECTED(00000003)\nunexpected eof while reading\nNegotiated TLS1.3 group: <NULL>\n"
    assert tls_handshake_incomplete(output)
    assert not negotiated_pqc_group(output)


def test_syslog_contract_constants() -> None:
    assert SYSLOG_SSL_PROFILE == "SYSLOG"
    assert SYSLOG_PORT == 6514


def test_cleartext_syslog_lines_detects_udp() -> None:
    cfg = "logging vrf MGMT host 10.0.0.1 514 protocol udp"
    assert cleartext_syslog_lines(cfg) == [cfg]


def test_cleartext_syslog_lines_detects_plain_tcp() -> None:
    cfg = "logging vrf MGMT host 10.0.0.1 514 protocol tcp"
    assert cleartext_syslog_lines(cfg) == [cfg]


def test_cleartext_syslog_lines_allows_tls() -> None:
    cfg = "\n".join(expected_syslog_host_lines(SYSLOG_SERVER_IPV4, SYSLOG_SERVER_IPV6))
    assert cleartext_syslog_lines(cfg) == []


def test_cleartext_syslog_lines_detects_host_without_protocol() -> None:
    cfg = "logging host 10.0.0.1"
    assert cleartext_syslog_lines(cfg) == [cfg]


def test_expected_syslog_host_line(ip_family: str) -> None:
    syslog_ip = SYSLOG_SERVER_IPV4 if ip_family == "ipv4" else SYSLOG_SERVER_IPV6
    line = expected_syslog_host_line(syslog_ip)
    assert "protocol tls ssl-profile SYSLOG" in line
    assert str(SYSLOG_PORT) in line
    assert syslog_ip in line


def test_check_switch_syslog_logging_config_requires_dual_stack_hosts() -> None:
    cfg = "\n".join(expected_syslog_host_lines(SYSLOG_SERVER_IPV4, SYSLOG_SERVER_IPV6))
    check_switch_syslog_logging_config(
        cfg,
        node="ceos1-both",
        syslog_ips=(SYSLOG_SERVER_IPV4, SYSLOG_SERVER_IPV6),
    )


def test_check_switch_syslog_logging_config_rejects_missing_ipv6_host() -> None:
    cfg = expected_syslog_host_line(SYSLOG_SERVER_IPV4)
    with pytest.raises(SyslogCheckError, match="expected syslog host line"):
        check_switch_syslog_logging_config(
            cfg,
            node="ceos1-both",
            syslog_ips=(SYSLOG_SERVER_IPV4, SYSLOG_SERVER_IPV6),
        )


def test_syslog_pqc_safe_group_constants() -> None:
    assert "X25519MLKEM768" in SYSLOG_TLS_PQC_SAFE_EOS_GROUPS
    assert "ecdh_x25519" in SYSLOG_TLS_PQC_SAFE_EOS_GROUPS
    assert "X25519MLKEM768" in SYSLOG_TLS_PQC_SAFE_OPENSSL_GROUPS
    assert "secp256r1" in SYSLOG_TLS_PQC_SAFE_OPENSSL_GROUPS


def test_tls_key_share_group_name() -> None:
    assert tls_key_share_group_name(TLS_KEY_SHARE_X25519MLKEM768) == PQC_GROUP
    assert tls_key_share_group_name(TLS_KEY_SHARE_X25519) == "x25519"
    assert is_pqc_hybrid_key_share_group(TLS_KEY_SHARE_X25519MLKEM768)
    assert not is_pqc_hybrid_key_share_group(TLS_KEY_SHARE_X25519)


def test_tshark_client_hello_filter_ipv4_mapped() -> None:
    filt = tshark_client_hello_filter("172.20.127.12")
    assert "ip.src == 172.20.127.12" in filt
    assert "ipv6.src == ::ffff:172.20.127.12" in filt


def test_tshark_client_hello_filter_ipv6() -> None:
    filt = tshark_client_hello_filter("2001:db8:127::12")
    assert "ipv6.src == 2001:db8:127::12" in filt


def test_tcpdump_captured_packet() -> None:
    assert tcpdump_captured_packet("listening on eth0\n1 packet captured\n")
    assert not tcpdump_captured_packet("listening on eth0\n0 packets captured\n")


def test_tcpdump_permission_denied() -> None:
    assert _tcpdump_permission_denied(
        "tcpdump: mgmt-bridge: You don't have permission to perform this capture"
    )
    assert _tcpdump_permission_denied("socket: Operation not permitted")
    assert not _tcpdump_permission_denied("listening on mgmt-bridge")


def test_tcpdump_argv_sudo() -> None:
    pcap = Path("/tmp/test.pcap")
    filt = "tcp port 6514 and host 172.20.127.11"
    plain = _tcpdump_argv("mgmt-bridge", pcap, filt, use_sudo=False)
    assert plain[0] == "tcpdump"
    assert "-Z" not in plain
    elevated = _tcpdump_argv("mgmt-bridge", pcap, filt, use_sudo=True)
    assert elevated[:2] == ["sudo", "tcpdump"]
    assert "-Z" in elevated
    assert elevated[-1] == filt


def test_announce_sudo_tcpdump_capture_once(capsys) -> None:
    from lab import syslog_checks

    syslog_checks._sudo_capture_announced = False
    syslog_checks._announce_sudo_tcpdump_capture("mgmt-bridge")
    syslog_checks._announce_sudo_tcpdump_capture("mgmt-bridge")

    output = capsys.readouterr().out
    assert output.count("using sudo fallback") == 1
    assert "enter password if prompted" in output


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
