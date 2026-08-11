"""Unit tests for EOS ``| json`` parsing helpers."""

from __future__ import annotations

import pytest

from lab.ceos_json import (
    CeosJsonError,
    assert_json_contains,
    extract_ckn_from_json,
    json_find_value,
    json_transport_ssl_profile,
    json_tree_contains,
    macsec_has_active_key,
    macsec_traffic_protected,
    mka_has_live_peers,
    parse_eos_json,
    ping_json_success,
    ping_text_success,
)


def test_parse_eos_json_rejects_empty() -> None:
    with pytest.raises(CeosJsonError, match="empty"):
        parse_eos_json("  ")


def test_json_tree_contains_finds_nested_values() -> None:
    payload = {"sslProfiles": [{"state": "valid", "groups": ["X25519MLKEM768"]}]}
    assert json_tree_contains(payload, "valid")
    assert json_tree_contains(payload, "X25519MLKEM768")
    assert not json_tree_contains(payload, "missing")


def test_assert_json_contains_raises_with_label() -> None:
    with pytest.raises(CeosJsonError, match="profile state"):
        assert_json_contains({"state": "broken"}, "valid", label="profile state")


def test_json_find_value_is_case_insensitive() -> None:
    payload = {"participants": [{"CKN": "abc123"}]}
    assert json_find_value(payload, "ckn") == "abc123"


def test_json_transport_ssl_profile() -> None:
    payload = {
        "enabled": True,
        "transports": {
            "default": {"enabled": True, "sslProfile": "GNMI"},
        },
    }
    assert json_transport_ssl_profile(payload) == "GNMI"
    assert json_transport_ssl_profile(payload, transport="missing") is None


def test_extract_ckn_from_json() -> None:
    payload = {"interfaces": [{"participants": [{"ckn": "e99229621701877766296aa8b76d7a07"}]}]}
    assert extract_ckn_from_json(payload) == "e99229621701877766296aa8b76d7a07"


def test_extract_ckn_from_json_participant_dict_keys() -> None:
    payload = {
        "interfaces": {
            "Ethernet1": {
                "participants": {
                    "deadbeef0123456789": {"success": False},
                    "ee494ffaffda19d85d223fcf686b7f6e": {
                        "success": True,
                        "details": {"sakTransmit": True, "livePeerList": ["peer1"]},
                    },
                }
            }
        }
    }
    assert extract_ckn_from_json(payload) == "ee494ffaffda19d85d223fcf686b7f6e"


def test_mka_has_live_peers() -> None:
    assert mka_has_live_peers({"livePeerList": ["peer1"]})
    assert not mka_has_live_peers({"livePeerList": []})


def test_macsec_traffic_protected() -> None:
    assert macsec_traffic_protected({"details": {"traffic": "Protected"}})
    assert macsec_traffic_protected({"traffic": "encrypted"})
    assert not macsec_traffic_protected({"traffic": "Unprotected"})


def test_macsec_has_active_key() -> None:
    assert macsec_has_active_key({"keyInUse": "deadbeef:1"})
    assert not macsec_has_active_key({"keyInUse": "None"})
    assert macsec_has_active_key({"keyMsgId": "faf6921cce5368e9ddd92eff", "keyNum": 1})


def test_ping_json_success() -> None:
    assert ping_json_success({"packetLoss": 0})
    assert ping_json_success({"results": [{"packetLossPercent": 0.0}]})
    assert not ping_json_success({"packetLoss": 100})


def test_ping_text_success() -> None:
    assert ping_text_success("3 packets transmitted, 3 received, 0% packet loss")
    assert ping_text_success("Success rate is 100 percent (5/5)")
    assert not ping_text_success("100% packet loss")
