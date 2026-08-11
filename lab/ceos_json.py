"""Parse and assert on Arista EOS ``show … | json`` output."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any


class CeosJsonError(RuntimeError):
    """Raised when EOS JSON output is invalid or missing expected data."""


def parse_eos_json(raw: str) -> Any:
    """Parse JSON emitted by EOS ``| json`` output."""
    text = raw.strip()
    if not text:
        raise CeosJsonError("empty EOS JSON output")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise CeosJsonError(f"invalid EOS JSON output: {exc}") from exc


def json_tree_values(obj: Any) -> Iterator[str]:
    """Yield string forms of keys and scalar values in a JSON tree."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, (int, float, bool)):
        yield str(obj)
    elif isinstance(obj, dict):
        for key, value in obj.items():
            yield str(key)
            yield from json_tree_values(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from json_tree_values(item)


def json_tree_contains(obj: Any, needle: str, *, case_sensitive: bool = True) -> bool:
    """Return True when *needle* appears in any scalar value under *obj*."""
    if case_sensitive:
        return any(needle in value for value in json_tree_values(obj))
    needle_lower = needle.lower()
    return any(needle_lower in value.lower() for value in json_tree_values(obj))


def assert_json_contains(
    obj: Any,
    needle: str,
    *,
    label: str,
    case_sensitive: bool = True,
) -> None:
    """Raise :class:`CeosJsonError` when *needle* is absent from *obj*."""
    if not json_tree_contains(obj, needle, case_sensitive=case_sensitive):
        raise CeosJsonError(f"{label}: expected {needle!r} in JSON output")


def json_find_value(obj: Any, key: str) -> Any | None:
    """Return the first value whose dict key matches *key* (case-insensitive)."""
    key_lower = key.lower()
    if isinstance(obj, dict):
        for dict_key, value in obj.items():
            if dict_key.lower() == key_lower:
                return value
        for value in obj.values():
            found = json_find_value(value, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = json_find_value(item, key)
            if found is not None:
                return found
    return None


def json_truthy(obj: Any, key: str) -> bool:
    """Return True when *key* resolves to a truthy EOS status value."""
    value = json_find_value(obj, key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"true", "success", "authorized", "enabled", "valid"}
    return False


def json_transport_ssl_profile(obj: Any, transport: str = "default") -> str | None:
    """Return ``sslProfile`` for a named transport under ``show management api … | json``."""
    transports = json_find_value(obj, "transports")
    if not isinstance(transports, dict):
        return None
    entry = transports.get(transport)
    if not isinstance(entry, dict):
        return None
    profile = entry.get("sslProfile")
    return profile if isinstance(profile, str) and profile else None


def extract_ckn_from_json(obj: Any) -> str:
    """Extract a hex CKN from ``show mac security participants detail | json``."""
    ckn = json_find_value(obj, "ckn")
    if isinstance(ckn, str) and re.fullmatch(r"[0-9a-f]+", ckn, re.IGNORECASE):
        return ckn

    participants = json_find_value(obj, "participants")
    if isinstance(participants, dict):
        successful = [
            (key, entry)
            for key, entry in participants.items()
            if isinstance(entry, dict) and entry.get("success") is True
        ]
        if successful:
            for key, entry in successful:
                details = entry.get("details")
                if isinstance(details, dict) and details.get("sakTransmit") is True:
                    return key
            return successful[0][0]
        for key in participants:
            if isinstance(key, str) and re.fullmatch(r"[0-9a-f]+", key, re.IGNORECASE):
                return key

    if isinstance(participants, list):
        for entry in participants:
            if not isinstance(entry, dict):
                continue
            ckn_val = entry.get("ckn") or entry.get("CKN")
            if isinstance(ckn_val, str) and re.fullmatch(r"[0-9a-f]+", ckn_val, re.IGNORECASE):
                return ckn_val

    raise CeosJsonError("expected CKN in mac security participants detail")


def mka_has_live_peers(obj: Any) -> bool:
    """Return True when MKA participant JSON lists at least one live peer."""
    peers = json_find_value(obj, "livePeerList")
    if peers is None:
        peers = json_find_value(obj, "livePeers")
    if isinstance(peers, list):
        return len(peers) > 0
    return json_tree_contains(obj, "Live peer list:") and not json_tree_contains(obj, "Live peer list: []")


def macsec_has_active_key(obj: Any) -> bool:
    """Return True when MACsec interface JSON reports an active SAK."""
    key = json_find_value(obj, "keyInUse")
    if key is None:
        key = json_find_value(obj, "sakInUse")
    if isinstance(key, str):
        return key.lower() not in ("none", "")
    if key is not None:
        return bool(key)

    key_msg_id = json_find_value(obj, "keyMsgId")
    if isinstance(key_msg_id, str) and key_msg_id:
        return True

    key_num = json_find_value(obj, "keyNum")
    if isinstance(key_num, (int, float)) and key_num > 0:
        return True

    if json_truthy(obj, "oldKeyTransmitting") or json_truthy(obj, "oldKeyReceiving"):
        return True

    return json_tree_contains(obj, "Key in use:") and not json_tree_contains(obj, "Key in use: None")


def macsec_traffic_protected(obj: Any) -> bool:
    """Return True when MACsec interface JSON reports protected/encrypted traffic."""
    traffic = json_find_value(obj, "traffic")
    if isinstance(traffic, str):
        return traffic.lower() in {"protected", "encrypted"}
    return json_tree_contains(obj, "Protected") or json_tree_contains(obj, "encrypted", case_sensitive=False)


_PING_SUCCESS_MARKERS = ("0% packet loss", "Success rate is 100 percent")


def ping_text_success(text: str) -> bool:
    """Return True when plain ``ping`` CLI output reports zero packet loss."""
    if "100% packet loss" in text:
        return False
    if "Success rate is 100 percent" in text:
        return True
    return "0% packet loss" in text


def ping_json_success(obj: Any) -> bool:
    """Return True when parsed ``ping … | json`` output reports zero packet loss."""
    for field in ("packetLoss", "packetLossPercent", "lossRate"):
        loss = json_find_value(obj, field)
        if loss is not None:
            try:
                return float(loss) == 0.0
            except (TypeError, ValueError):
                pass
    return any(json_tree_contains(obj, marker) for marker in _PING_SUCCESS_MARKERS)
