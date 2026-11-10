"""Unit tests for live MACsec/MKA check helpers."""

from __future__ import annotations

import json
import shlex
import subprocess
from unittest.mock import patch

import pytest

from lab.test_macsec_dot1x import (
    AUTHENTICATOR,
    DOT1X_EAP_IDENTITY,
    MacsecCheckError,
    check_dot1x_reauth_cycle,
    check_matching_mka_ckn,
    count_radius_login_ok,
    check_mka_participants,
    extract_ckn,
    run_macsec_checks,
)
from lab.topology_contract import DOT1X_EAP_SSL_PROFILE, DOT1X_REAUTH_PERIOD_SEC, DOT1X_SUPPLICANT_PROFILE, MACSEC_PROFILE


@pytest.mark.parametrize(
    "lines,expected",
    [
        ("Auth: Login OK: [ceos2-pqc]\n", 1),
        ("Auth: (59) Login OK: [ceos2-pqc]\n", 1),
        ("Auth: Login OK: [old]\nAuth: (60) Login OK: [new]\nAuth: (61) Login incorrect\n", 2),
        ("Auth: (62) Login incorrect\n", 0),
    ],
)
def test_count_radius_login_ok_accepts_request_ids(lines, expected, tmp_path) -> None:
    logfile = tmp_path / "radius.log"
    logfile.write_text(lines)

    def execute_count(container, command, **kwargs):
        command = command.replace("/var/log/radius/radius.log", shlex.quote(str(logfile)))
        return subprocess.run(["sh", "-c", command], capture_output=True, text=True)

    with patch("lab.test_macsec_dot1x.docker_exec", side_effect=execute_count):
        assert count_radius_login_ok("radius") == expected


def _dot1x_config_text(*, authenticator: bool) -> tuple[str, str]:
    if authenticator:
        section = (
            "aaa authentication dot1x default group RADIUS\n"
            "dot1x system-auth-control\n"
        )
        interface = (
            f"interface Ethernet1\n"
            f"   dot1x pae authenticator\n"
            f"   dot1x reauthentication\n"
            f"   dot1x timeout reauth-period {DOT1X_REAUTH_PERIOD_SEC}\n"
            f"   mac security profile {MACSEC_PROFILE}\n"
        )
        return section, interface
    section = (
        f"dot1x\n"
        f"   supplicant profile {DOT1X_SUPPLICANT_PROFILE}\n"
        f"      identity {DOT1X_EAP_IDENTITY}\n"
        f"      eap-method tls\n"
        f"      ssl profile {DOT1X_EAP_SSL_PROFILE}\n"
    )
    interface = (
        f"interface Ethernet1\n"
        f"   dot1x pae supplicant {DOT1X_SUPPLICANT_PROFILE}\n"
        f"   mac security profile {MACSEC_PROFILE}\n"
    )
    return section, interface


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


@pytest.mark.parametrize("rotate_during_check", [False, True])
def test_run_macsec_checks_happy_path(capsys, rotate_during_check) -> None:
    state_json = _macsec_state_json(ckn="abcdef0123456789")
    participant_reads = 0

    def fake_ceos_cli(container: str, commands: str, **kwargs: object) -> str:
        nonlocal participant_reads
        if "show running-config | include dot1x" in commands:
            section, _interface = _dot1x_config_text(authenticator="ceos1" in container)
            return section
        if "show running-config | section dot1x" in commands:
            section, _interface = _dot1x_config_text(authenticator="ceos1" in container)
            return section
        if "show running-config interface Ethernet1" in commands:
            if "ceos3-qkd" in container:
                return "interface Ethernet1\n   mac security profile quadra-slave\n"
            _section, interface = _dot1x_config_text(authenticator="ceos1" in container)
            return interface
        if "show running-config interface Ethernet2" in commands:
            return f"interface Ethernet2\n   mac security profile quadra-master\n"
        if "show running-config | section mac security" in commands:
            return (
                "mac security\n"
                "   profile quadra-master\n"
                "      cipher aes256-gcm-xpn\n"
                "      key source sak static\n"
                "   profile quadra-slave\n"
                "      cipher aes256-gcm-xpn\n"
                "      key source sak static\n"
            )
        if "| json" not in commands:
            if "ping " in commands:
                return "Success rate is 100 percent"
            raise AssertionError(f"unexpected plain-text ceos_cli commands: {commands!r}")
        if "show dot1x hosts" in commands:
            return json.dumps(state_json["dot1xHosts"])
        if "show dot1x interface" in commands:
            return json.dumps(state_json["dot1xInterfaceDetail"])
        if "show dot1x supplicant" in commands:
            return json.dumps(state_json["dot1xSupplicant"])
        if "show mac security interface Ethernet1" in commands:
            return json.dumps(state_json["macSecurityInterface"])
        if "show mac security interface Ethernet2" in commands:
            return json.dumps(state_json["macSecurityInterface"])
        if "show mac security participants" in commands:
            participant_reads += 1
            if rotate_during_check and participant_reads == 1:
                return json.dumps(_macsec_state_json(ckn="aaa")["macSecurityParticipants"])
            return json.dumps(state_json["macSecurityParticipants"])
        raise AssertionError(f"unexpected ceos_cli commands: {commands!r}")

    with (
        patch("lab.test_macsec_dot1x.ceos_cli", side_effect=fake_ceos_cli),
        patch("lab.test_pqc_connections.ceos_cli", side_effect=fake_ceos_cli),
        patch("lab.test_macsec_dot1x.time.sleep") as sleep,
    ):
        run_macsec_checks(clab_name="quantum-safe", mgmt_subnet="172.20.127.0/24")
        assert sleep.call_count == int(rotate_during_check)

    output = capsys.readouterr().out
    assert "MACsec: ✓" in output
    assert AUTHENTICATOR in output


def test_run_macsec_checks_ckn_mismatch(capsys) -> None:
    state_json = _macsec_state_json(ckn="aaa")

    def fake_ceos_cli(container: str, commands: str, **kwargs: object) -> str:
        if "show mac security participants" in commands:
            ckn = "aaa" if "ceos1-both" in container else "bbb"
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
            return "Success rate is 100 percent"
        if "show running-config" in commands:
            section, _interface = _dot1x_config_text(authenticator=True)
            return section
        raise AssertionError(commands)

    with (
        patch("lab.test_macsec_dot1x.ceos_cli", side_effect=fake_ceos_cli),
        patch("lab.test_pqc_connections.ceos_cli", side_effect=fake_ceos_cli),
        patch("lab.test_macsec_dot1x.time.sleep"),
    ):
        with pytest.raises(MacsecCheckError, match="CKN mismatch"):
            run_macsec_checks(clab_name="quantum-safe", mgmt_subnet="172.20.127.0/24", skip_config=True)


def test_check_mka_participants_retries_until_peers_appear() -> None:
    call_count = {"n": 0}
    ckn = "abcdef0123456789"

    def fake_ceos_show_json(_container: str, command: str, **kwargs: object):
        assert "show mac security participants" in command
        call_count["n"] += 1
        peers = [] if call_count["n"] < 3 else ["peer1"]
        return {"participants": [{"ckn": ckn, "success": True, "livePeerList": peers}]}

    with patch("lab.test_macsec_dot1x.ceos_show_json", side_effect=fake_ceos_show_json):
        with patch("lab.test_macsec_dot1x.time.sleep") as sleep:
            result = check_mka_participants("clab-test-ceos1-both", AUTHENTICATOR)
    assert result == ckn
    assert call_count["n"] == 3
    assert sleep.call_count == 2


def test_check_matching_mka_ckn_retries_principal_transition(capsys) -> None:
    def snapshot(principal: str) -> dict:
        return {"interfaces": {"Ethernet1": {"participants": {
            ckn: {
                "success": True,
                "principalActor": ckn == principal,
                "details": {"sakTransmit": True, "livePeerList": ["peer1"]},
            }
            for ckn in ("aaa", "bbb")
        }}}}

    with (
        patch("lab.test_macsec_dot1x.ceos_show_json", side_effect=[
            snapshot("aaa"), snapshot("bbb"), snapshot("bbb"), snapshot("bbb"),
        ]) as show,
        patch("lab.test_macsec_dot1x.time.sleep") as sleep,
    ):
        assert check_matching_mka_ckn("auth", "supp") == "bbb"

    assert [call.args[0] for call in show.call_args_list] == ["auth", "supp", "auth", "supp"]
    sleep.assert_called_once_with(2)
    output = capsys.readouterr().out
    assert "matching CKN on both peers (bbb)" in output
    assert "aaa" not in output


@pytest.mark.parametrize("recover", [False, True])
def test_check_matching_mka_ckn_handles_missing_peers(recover) -> None:
    valid = _macsec_state_json(ckn="aaa")["macSecurityParticipants"]
    empty = {"participants": [{"ckn": "aaa", "success": True, "livePeerList": []}]}
    samples = [valid, empty, valid, valid if recover else empty]
    with (
        patch("lab.test_macsec_dot1x.MKA_POLL_ATTEMPTS", 2),
        patch("lab.test_macsec_dot1x.ceos_show_json", side_effect=samples) as show,
        patch("lab.test_macsec_dot1x.time.sleep"),
    ):
        if recover:
            assert check_matching_mka_ckn("auth", "supp") == "aaa"
        else:
            with pytest.raises(MacsecCheckError, match="ceos2-pqc: MKA live peer list is empty"):
                check_matching_mka_ckn("auth", "supp")
    assert show.call_count == 4


def test_check_matching_mka_ckn_rejects_matches_from_different_attempts() -> None:
    samples = [
        _macsec_state_json(ckn=ckn)["macSecurityParticipants"]
        for ckn in ("aaa", "bbb", "bbb", "ccc", "ccc", "ddd")
    ]
    with (
        patch("lab.test_macsec_dot1x.MKA_POLL_ATTEMPTS", 3),
        patch("lab.test_macsec_dot1x.ceos_show_json", side_effect=samples) as show,
        patch("lab.test_macsec_dot1x.time.sleep") as sleep,
    ):
        with pytest.raises(MacsecCheckError, match="CKN mismatch: ceos1-both='ccc' vs ceos2-pqc='ddd'.*3 paired"):
            check_matching_mka_ckn("auth", "supp")
    assert show.call_count == 6
    assert sleep.call_count == 2


def test_check_dot1x_reauth_cycle_happy_path(capsys) -> None:
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
        patch("lab.test_macsec_dot1x.time.sleep") as sleep,
        patch("lab.test_macsec_dot1x.docker_exec", side_effect=fake_docker_exec),
        patch("lab.test_pqc_connections.ceos_cli", side_effect=fake_ceos_cli),
    ):
        check_dot1x_reauth_cycle(
            targets,
            "clab-test-ceos1-both",
            "clab-test-ceos2-pqc",
            "abcdef0123456789",
        )
        sleep.assert_called_once_with(DOT1X_REAUTH_PERIOD_SEC + 15)

    output = capsys.readouterr().out
    assert "CKN unchanged (abcdef0123456789)" in output


@pytest.mark.parametrize("rotate_during_check", [False, True])
def test_check_dot1x_reauth_cycle_allows_ckn_rotation(capsys, rotate_during_check) -> None:
    """EAP-TLS reauth derives a new MSK, so CKN may change; peers must still match."""
    state_json = _macsec_state_json(ckn="2de6708f95996d6d1357f08347db26df")
    login_ok_counts = iter([2, 3])
    participant_reads = 0

    def fake_ceos_cli(_container: str, commands: str, **kwargs: object) -> str:
        nonlocal participant_reads
        if "show dot1x hosts" in commands:
            return json.dumps(state_json["dot1xHosts"])
        if "show dot1x interface" in commands:
            return json.dumps(state_json["dot1xInterfaceDetail"])
        if "show dot1x supplicant" in commands:
            return json.dumps(state_json["dot1xSupplicant"])
        if "show mac security participants" in commands:
            participant_reads += 1
            if rotate_during_check and participant_reads == 1:
                return json.dumps(_macsec_state_json(ckn="aaa")["macSecurityParticipants"])
            return json.dumps(state_json["macSecurityParticipants"])
        raise AssertionError(f"unexpected ceos_cli commands: {commands!r}")

    def fake_docker_exec(container: str, command: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert "Login OK" in command
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=str(next(login_ok_counts)), stderr="")

    targets = type("Targets", (), {"radius_container": "clab-test-radius"})()

    with (
        patch("lab.test_macsec_dot1x.time.sleep"),
        patch("lab.test_macsec_dot1x.docker_exec", side_effect=fake_docker_exec),
        patch("lab.test_pqc_connections.ceos_cli", side_effect=fake_ceos_cli),
    ):
        check_dot1x_reauth_cycle(
            targets,
            "clab-test-ceos1-both",
            "clab-test-ceos2-pqc",
            "117e6818b717ef6d25f1cde018b39555",
        )

    output = capsys.readouterr().out
    assert "CKN rotated" in output
    assert "117e6818b717ef6d25f1cde018b39555" in output
    assert "2de6708f95996d6d1357f08347db26df" in output


def test_check_dot1x_reauth_cycle_raises_on_peer_ckn_mismatch() -> None:
    state_json = _macsec_state_json(ckn="aaa")
    login_ok_counts = iter([2, 3])

    def fake_ceos_cli(container: str, commands: str, **kwargs: object) -> str:
        if "show mac security participants" in commands:
            ckn = "aaa" if "ceos1-both" in container else "bbb"
            payload = {"participants": [{"ckn": ckn, "success": True, "livePeerList": ["peer"]}]}
            return json.dumps(payload)
        if "show dot1x hosts" in commands:
            return json.dumps(state_json["dot1xHosts"])
        if "show dot1x interface" in commands:
            return json.dumps(state_json["dot1xInterfaceDetail"])
        if "show dot1x supplicant" in commands:
            return json.dumps(state_json["dot1xSupplicant"])
        raise AssertionError(commands)

    def fake_docker_exec(_container: str, _command: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout=str(next(login_ok_counts)), stderr=""
        )

    targets = type("Targets", (), {"radius_container": "clab-test-radius"})()

    with (
        patch("lab.test_macsec_dot1x.time.sleep"),
        patch("lab.test_macsec_dot1x.docker_exec", side_effect=fake_docker_exec),
        patch("lab.test_pqc_connections.ceos_cli", side_effect=fake_ceos_cli),
    ):
        with pytest.raises(MacsecCheckError, match="CKN mismatch"):
            check_dot1x_reauth_cycle(
                targets,
                "clab-test-ceos1-both",
                "clab-test-ceos2-pqc",
                "aaa",
            )


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
        patch("lab.test_macsec_dot1x.time.sleep"),
        patch("lab.test_macsec_dot1x.docker_exec", side_effect=fake_docker_exec),
        patch("lab.test_pqc_connections.ceos_cli", side_effect=fake_ceos_cli),
    ):
        with pytest.raises(MacsecCheckError, match="expected additional RADIUS Login OK"):
            check_dot1x_reauth_cycle(
                targets,
                "clab-test-ceos1-both",
                "clab-test-ceos2-pqc",
                "abcdef0123456789",
            )
