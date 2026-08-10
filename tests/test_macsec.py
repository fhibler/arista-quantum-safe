"""Unit tests for live MACsec/MKA check helpers."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from lab.test_macsec import (
    AUTHENTICATOR,
    DOT1X_EAP_IDENTITY,
    MacsecCheckError,
    extract_ckn,
    run_macsec_checks,
)


def test_extract_ckn_parses_hex_value() -> None:
    output = "Interface: Ethernet1\n    CKN: e99229621701877766296aa8b76d7a07\n      Success: True"
    assert extract_ckn(output) == "e99229621701877766296aa8b76d7a07"


def test_extract_ckn_raises_when_missing() -> None:
    with pytest.raises(MacsecCheckError, match="CKN"):
        extract_ckn("Interface: Ethernet1\n    Success: True")


def test_run_macsec_checks_happy_path(capsys) -> None:
    participants = (
        "Interface: Ethernet1\n"
        "    CKN: abcdef0123456789\n"
        "      Success: True\n"
        '      Live peer list: ["peer1"]'
    )
    macsec_detail = (
        "Controlled port: True\n"
        "Traffic: encrypted\n"
        "Key in use: deadbeef12345678:1"
    )

    def fake_ceos_cli(container: str, commands: str, **kwargs: object) -> str:
        if "show dot1x hosts" in commands:
            return f"Et1  mac  {DOT1X_EAP_IDENTITY}  EAPOL  SUCCESS"
        if "show dot1x interface" in commands:
            return "Port status: Authorized"
        if "show dot1x supplicant" in commands:
            return (
                f"Identity: {DOT1X_EAP_IDENTITY}\n"
                "Status: success\n"
                "EAP method: tls\n"
                "SSL profile: DOT1X\n"
                "TLS key establishment group: X25519MLKEM768"
            )
        if "show mac security interface" in commands:
            return macsec_detail
        if "show mac security participants" in commands:
            return participants
        if "show running-config | section dot1x" in commands:
            return (
                "aaa authentication dot1x default group RADIUS\n"
                "supplicant profile macsec-sp\n"
                "identity ceos2\n"
                "eap-method tls\n"
                "ssl profile DOT1X"
            )
        if "show running-config interface Ethernet1" in commands:
            return (
                "dot1x pae authenticator\n"
                "dot1x reauthentication\n"
                "dot1x timeout reauth-period 60\n"
                "dot1x pae supplicant macsec-sp\n"
                "mac security profile dynamic"
            )
        if "ping 10.255.0.2" in commands or "ping 10.255.0.1" in commands:
            return "3 packets transmitted, 3 received, 0% packet loss"
        raise AssertionError(f"unexpected ceos_cli commands: {commands!r}")

    with patch("lab.test_macsec.ceos_cli", side_effect=fake_ceos_cli):
        run_macsec_checks(clab_name="qkd-macsec-radius", mgmt_subnet="172.20.127.0/24")

    output = capsys.readouterr().out
    assert "MACsec: OK" in output
    assert AUTHENTICATOR in output


def test_run_macsec_checks_ckn_mismatch(capsys) -> None:
    call_count = {"n": 0}

    def fake_ceos_cli(_container: str, commands: str, **kwargs: object) -> str:
        if "show mac security participants" in commands:
            call_count["n"] += 1
            ckn = "aaa" if call_count["n"] == 1 else "bbb"
            return f"CKN: {ckn}\nSuccess: True\nLive peer list: [\"peer\"]"
        if "show dot1x hosts" in commands:
            return f"{DOT1X_EAP_IDENTITY} SUCCESS"
        if "show dot1x interface" in commands:
            return "Port status: Authorized"
        if "show dot1x supplicant" in commands:
            return "Identity: ceos2\nStatus: success\nEAP method: tls\nSSL profile: DOT1X\nTLS key establishment group: X25519MLKEM768"
        if "show mac security interface" in commands:
            return "Controlled port: True\nTraffic: encrypted\nKey in use: key:1"
        if "show running-config" in commands:
            return "dot1x\nmac security profile dynamic"
        raise AssertionError(commands)

    with patch("lab.test_macsec.ceos_cli", side_effect=fake_ceos_cli):
        with pytest.raises(MacsecCheckError, match="CKN mismatch"):
            run_macsec_checks(clab_name="qkd-macsec-radius", mgmt_subnet="172.20.127.0/24", skip_config=True)
