"""Regression checks against false positive QuaDRA TLS measurements."""

from __future__ import annotations

import csv
import io
import subprocess
from unittest.mock import patch

import pytest

from lab.quadra_tls import (
    FIELDS, HELLO_RETRY_RANDOM, QuadraTlsError, capture_quadra_tls,
    parse_quadra_tls_handshakes, quadra_tls_peer, successful_key_requests, verify_quadra_tls,
)

PEER = quadra_tls_peer("ceos1-both", "172.20.127.51:8010")


def hello(kind="1", *, stream="0", group="4588", version="0x0304", random="abcd", **changes):
    client = kind == "1"
    row = {
        "frame.number": "4" if client else "6", "frame.time_epoch": "1794345395.388562000",
        "ip.src": "172.20.127.11" if client else "172.20.127.51", "ipv6.src": "",
        "ip.dst": "172.20.127.51" if client else "172.20.127.11", "ipv6.dst": "",
        "tcp.srcport": "52184" if client else "8010", "tcp.dstport": "8010" if client else "52184",
        "tcp.stream": stream, "tls.handshake.type": kind, "tls.handshake.random": random,
        "tls.handshake.extensions.supported_version": version,
        "tls.handshake.extensions_key_share_group": group,
        "tls.handshake.extensions_supported_group": "0x11ec,0x001d,0x0017" if client else "",
        "tls.handshake.ciphersuite": "0x1302,0x1303,0x1301" if client else "0x1302",
    }
    return row | changes


def tsv(*rows):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=FIELDS, delimiter="\t")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def test_server_selection_not_hybrid_client_offer_controls_result():
    result = parse_quadra_tls_handshakes(tsv(hello(), hello("2", group="29")), PEER)
    assert result[0].offered_groups == (4588, 29, 23)
    assert not result[0].pqc_confirmed


def test_client_hello_and_retry_request_do_not_count_as_negotiation():
    assert parse_quadra_tls_handshakes(tsv(hello()), PEER) == []
    assert parse_quadra_tls_handshakes(tsv(hello(), hello("2", random=HELLO_RETRY_RANDOM)), PEER) == []
    result = parse_quadra_tls_handshakes(tsv(
        hello(), hello("2", random=HELLO_RETRY_RANDOM), hello(), hello("2"),
    ), PEER)
    assert len(result) == 1 and result[0].pqc_confirmed


def test_tls13_must_be_selected_by_server():
    result = parse_quadra_tls_handshakes(tsv(hello(), hello("2", version="")), PEER)
    assert not result[0].pqc_confirmed


def test_different_stream_or_endpoint_does_not_satisfy_check():
    assert parse_quadra_tls_handshakes(tsv(hello(), hello("2", stream="1")), PEER) == []
    assert parse_quadra_tls_handshakes(tsv(hello(), hello("2", **{"tcp.srcport": "8020"})), PEER) == []


def test_mixed_classical_and_hybrid_connections_remain_visible():
    result = parse_quadra_tls_handshakes(tsv(
        hello(), hello("2", group="23"), hello(stream="1"), hello("2", stream="1"),
    ), PEER)
    assert [h.pqc_confirmed for h in result] == [False, True]


def test_success_log_requires_captured_source_correct_endpoint_and_http_200():
    valid = '172.20.127.11 - - [10/Nov/2026 21:16:35] "POST /api/v1/keys/sae/enc_keys HTTP/1.1" 200 -'
    logs = "\n".join([
        valid, valid.replace("172.20.127.11", "172.20.127.51"),
        valid.replace("200 -", "500 -"), valid.replace("enc_keys", "dec_keys"),
    ])
    assert successful_key_requests(logs, PEER, {"172.20.127.11"}) == [valid]


def test_ipv6_endpoint_and_handshake():
    peer = quadra_tls_peer("ceos3-qkd", "[2001:db8:127::52]:8020")
    client = hello(**{"ip.src": "", "ip.dst": "", "ipv6.src": "2001:db8:127::13",
                      "ipv6.dst": peer.server_ip, "tcp.dstport": "8020"})
    server = hello("2", **{"ip.src": "", "ip.dst": "", "ipv6.src": peer.server_ip,
                           "ipv6.dst": "2001:db8:127::13", "tcp.srcport": "8020"})
    assert parse_quadra_tls_handshakes(tsv(client, server), peer)[0].pqc_confirmed


@pytest.mark.parametrize("endpoint", ["", "host:8010", "172.20.127.51", "172.20.127.51:8010/path"])
def test_invalid_endpoint_rejected(endpoint):
    with pytest.raises(QuadraTlsError, match="invalid QuaDRA KME endpoint"):
        quadra_tls_peer("ceos1-both", endpoint)


def test_empty_capture_or_missing_tcpdump_is_unverified(tmp_path):
    with patch("lab.quadra_tls.subprocess.run", return_value=subprocess.CompletedProcess([], 127)):
        with pytest.raises(QuadraTlsError, match="TLS KEX unverified"):
            capture_quadra_tls(PEER, clab_name="lab", duration=1, output_dir=tmp_path)


@pytest.mark.parametrize("kind", ["missing", "classical", "no_request"])
def test_verification_fails_closed_and_saves_evidence(tmp_path, kind):
    rows = [] if kind == "missing" else parse_quadra_tls_handshakes(tsv(
        hello(), hello("2", group="23" if kind == "classical" else "4588"),
    ), PEER)
    log = '' if kind == "no_request" else '172.20.127.11 - - [10/Nov/2026 21:16:35] "POST /api/v1/keys/sae/enc_keys HTTP/1.1" 200 -'
    with (
        patch("lab.quadra_tls.capture_quadra_tls", return_value=tmp_path / "capture.pcap"),
        patch("lab.quadra_tls.decode_quadra_tls", return_value=rows),
        patch("lab.quadra_tls.subprocess.run", return_value=subprocess.CompletedProcess([], 0, log, "")),
    ):
        with pytest.raises(QuadraTlsError, match="unverified|not PQC-safe"):
            verify_quadra_tls([PEER], clab_name="lab", output_dir=tmp_path)
    assert (tmp_path / "result.json").is_file()


def test_explicit_measurement_cannot_skip_when_extension_missing():
    from lab.test_macsec_qkd import QkdCheckError, run_qkd_checks

    with patch("lab.test_macsec_qkd.quadra_installed_on_nodes", return_value=False):
        with pytest.raises(QkdCheckError, match="unverified"):
            run_qkd_checks(clab_name="lab", verify_tls=True)


def test_cli_tls_measurement_cannot_turn_a_skip_into_success():
    from lab.test_macsec_qkd import QkdSkip, main

    with patch("lab.test_macsec_qkd.run_qkd_checks", side_effect=QkdSkip("extension unavailable")):
        assert main(["--verify-tls"]) == 1
        assert main([]) == 0
