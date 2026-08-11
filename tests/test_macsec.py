"""Unit tests for live MACsec/MKA check helpers."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from lab.test_macsec import (
    AUTHENTICATOR,
    DOT1X_EAP_IDENTITY,
    MacsecCheckError,
    check_dot1x_reauth_cycle,
    extract_ckn,
    run_macsec_checks,
)
from lab.topology_contract import DOT1X_EAP_SSL_PROFILE, DOT1X_REAUTH_PERIOD_SEC, DOT1X_SUPPLICANT_PROFILE, MACSEC_PROFILE


def _dot1x_config_json(*, authenticator: bool) -> dict:
    if authenticator:
        return {
            "aaa": {"authentication": {"dot1x": {"default": {"group": "RADIUS"}}}},
            "interfaces": {
                "Ethernet1": {
                    "dot1x": {
                        "pae": "authenticator",
                        "reauthentication": True,
                        "timeout": {"reauthPeriod": DOT1X_REAUTH_PERIOD_SEC},
                    },
                    "macSecurity": {"profile": MACSEC_PROFILE},
                }
            },
        }
    return {
        "dot1x": {
            "supplicantProfiles": {
                DOT1X_SUPPLICANT_PROFILE: {
                    "identity": DOT1X_EAP_IDENTITY,
                    "eapMethod": "tls",
                    "sslProfile": DOT1X_EAP_SSL_PROFILE,
                }
            }
        },
        "interfaces": {
            "Ethernet1": {
                "dot1x": {"pae": {"supplicant": DOT1X_SUPPLICANT_PROFILE}},
            }
        },
    }


def _macsec_state_json(*, ckn: str) -> dict:
    return {
        "dot1xHosts": [{"identity": DOT1X_EAP_IDENTITY, "status": "SUCCESS"}],
        "dot1xInterfaceDetail": {"portStatus": "Authorized"},
        "dot1xSupplicant": {
            "identity": DOT1X_EAP_IDENTITY,
            "status": "success",
            "eapMethod": "tls",
            "sslProfile": DOT1X_EAP_SSL_PROFILE,
            "tls13Groups": ["X25519MLKEM768"],
        },
        "macSecurityInterface": {
            "controlledPort": True,
            "traffic": "encrypted",
            "keyInUse": "deadbeef12345678:1",
        },
        "macSecurityParticipants": {
            "participants": [{"ckn": ckn, "success": True, "livePeerList": ["peer1"]}],
        },
        "ping": {"packetLoss": 0},
    }


def test_extract_ckn_parses_hex_value() -> None:
    output = "Interface: Ethernet1\n    CKN: e99229621701877766296aa8b76d7a07\n      Success: True"
    assert extract_ckn(output) == "e99229621701877766296aa8b76d7a07"


def test_extract_ckn_parses_json_value() -> None:
    output = json.dumps({"participants": [{"ckn": "e99229621701877766296aa8b76d7a07"}]})
    assert extract_ckn(output) == "e99229621701877766296aa8b76d7a07"


def test_extract_ckn_raises_when_missing() -> None:
    with pytest.raises(MacsecCheckError, match="CKN"):
        extract_ckn("Interface: Ethernet1\n    Success: True")


def test_run_macsec_checks_happy_path(capsys) -> None:
    state_json = _macsec_state_json(ckn="abcdef0123456789")

    def fake_ceos_cli(container: str, commands: str, **kwargs: object) -> str:
        if "| json" not in commands:
            raise AssertionError(f"expected | json in commands: {commands!r}")
        if "show running-config | section dot1x" in commands:
            payload = _dot1x_config_json(authenticator="ceos1" in container)
            return json.dumps(payload)
        if "show running-config interface Ethernet1" in commands:
            payload = _dot1x_config_json(authenticator="ceos1" in container)
            return json.dumps(payload["interfaces"]["Ethernet1"])
        if "show dot1x hosts" in commands:
            return json.dumps(state_json["dot1xHosts"])
        if "show dot1x interface" in commands:
            return json.dumps(state_json["dot1xInterfaceDetail"])
        if "show dot1x supplicant" in commands:
            return json.dumps(state_json["dot1xSupplicant"])
        if "show mac security interface" in commands:
            return json.dumps(state_json["macSecurityInterface"])
        if "show mac security participants" in commands:
            return json.dumps(state_json["macSecurityParticipants"])
        if "ping " in commands:
            return json.dumps(state_json["ping"])
        raise AssertionError(f"unexpected ceos_cli commands: {commands!r}")

    with patch("lab.test_pqc_connections.ceos_cli", side_effect=fake_ceos_cli):
        run_macsec_checks(clab_name="quantum-safe", mgmt_subnet="172.20.127.0/24")

    output = capsys.readouterr().out
    assert "MACsec: OK" in output
    assert AUTHENTICATOR in output


def test_run_macsec_checks_ckn_mismatch(capsys) -> None:
    call_count = {"n": 0}
    state_json = _macsec_state_json(ckn="aaa")

    def fake_ceos_cli(_container: str, commands: str, **kwargs: object) -> str:
        if "show mac security participants" in commands:
            call_count["n"] += 1
            ckn = "aaa" if call_count["n"] == 1 else "bbb"
            payload = {"participants": [{"ckn": ckn, "success": True, "livePeerList": ["peer"]}]}
            return json.dumps(payload)
        if "show dot1x hosts" in commands:
            return json.dumps(state_json["dot1xHosts"])
        if "show dot1x interface" in commands:
            return json.dumps(state_json["dot1xInterfaceDetail"])
        if "show dot1x supplicant" in commands:
            return json.dumps(state_json["dot1xSupplicant"])
        if "show mac security interface" in commands:
            return json.dumps(state_json["macSecurityInterface"])
        if "ping " in commands:
            return json.dumps(state_json["ping"])
        if "show running-config" in commands:
            return json.dumps({"dot1x": True, "macSecurity": {"profile": MACSEC_PROFILE}})
        raise AssertionError(commands)

    with patch("lab.test_pqc_connections.ceos_cli", side_effect=fake_ceos_cli):
        with pytest.raises(MacsecCheckError, match="CKN mismatch"):
            run_macsec_checks(clab_name="quantum-safe", mgmt_subnet="172.20.127.0/24", skip_config=True)


def test_check_dot1x_reauth_cycle_happy_path() -> None:
    state_json = _macsec_state_json(ckn="abcdef0123456789")
    login_ok_counts = iter([2, 3])

    def fake_ceos_cli(_container: str, commands: str, **kwargs: object) -> str:
        if "show dot1x hosts" in commands:
            return json.dumps(state_json["dot1xHosts"])
        if "show dot1x interface" in commands:
            return json.dumps(state_json["dot1xInterfaceDetail"])
        if "show dot1x supplicant" in commands:
            return json.dumps(state_json["dot1xSupplicant"])
        if "show mac security participants" in commands:
            return json.dumps(state_json["macSecurityParticipants"])
        raise AssertionError(f"unexpected ceos_cli commands: {commands!r}")

    def fake_docker_exec(container: str, command: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert "Login OK" in command
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=str(next(login_ok_counts)), stderr="")

    targets = type("Targets", (), {"radius_container": "clab-test-radius"})()

    with (
        patch("lab.test_macsec.time.sleep") as sleep,
        patch("lab.test_macsec.docker_exec", side_effect=fake_docker_exec),
        patch("lab.test_pqc_connections.ceos_cli", side_effect=fake_ceos_cli),
    ):
        check_dot1x_reauth_cycle(
            targets,
            "clab-test-ceos1-both",
            "clab-test-ceos2-pqc",
            "abcdef0123456789",
        )
        sleep.assert_called_once_with(DOT1X_REAUTH_PERIOD_SEC + 15)


def test_check_dot1x_reauth_cycle_raises_when_login_ok_unchanged() -> None:
    state_json = _macsec_state_json(ckn="abcdef0123456789")

    def fake_ceos_cli(_container: str, commands: str, **kwargs: object) -> str:
        if "show dot1x hosts" in commands:
            return json.dumps(state_json["dot1xHosts"])
        if "show dot1x interface" in commands:
            return json.dumps(state_json["dot1xInterfaceDetail"])
        if "show dot1x supplicant" in commands:
            return json.dumps(state_json["dot1xSupplicant"])
        if "show mac security participants" in commands:
            return json.dumps(state_json["macSecurityParticipants"])
        raise AssertionError(commands)

    def fake_docker_exec(_container: str, _command: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="1", stderr="")

    targets = type("Targets", (), {"radius_container": "clab-test-radius"})()

    with (
        patch("lab.test_macsec.time.sleep"),
        patch("lab.test_macsec.docker_exec", side_effect=fake_docker_exec),
        patch("lab.test_pqc_connections.ceos_cli", side_effect=fake_ceos_cli),
    ):
        with pytest.raises(MacsecCheckError, match="expected additional RADIUS Login OK"):
            check_dot1x_reauth_cycle(
                targets,
                "clab-test-ceos1-both",
                "clab-test-ceos2-pqc",
                "abcdef0123456789",
            )
