"""Unit tests for QuaDRA / QKD live check helpers."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from lab.test_macsec_qkd import (
    MASTER,
    STATIC_MACSEC_POLL_ATTEMPTS,
    STATIC_MACSEC_POLL_INTERVAL_SEC,
    QkdCheckError,
    assert_plain_sak_key_exchange,
    assert_static_sak_peer_mapping,
    check_agent_role,
    check_kme_key_request_logs,
    check_master_rotation_schedule,
    find_rotation_success_log,
    note_rotation_success_log,
    check_static_macsec_interface,
    extension_installed,
    kme_key_request_lines,
    parse_daemon_quadra_status,
    parse_static_sak_profile,
    run_qkd_checks,
)
from lab.topology_contract import (
    QUADRA_KEY_RX,
    QUADRA_MACSEC_INTF,
    QUADRA_KEY_TX,
    QUADRA_MACSEC_PROFILE_MASTER,
    QUADRA_MACSEC_PROFILE_SLAVE,
    QUADRA_SC_RX_ID,
    QUADRA_SC_TX_ID,
)

SAMPLE_MASTER_DAEMON = """
Agent: quadra (running with PID 2693)
Uptime: 0:06:41 (Start time: Tue Aug 11 13:10:14 2026)
Configuration:
Option         Value
-------------- -----------------------------------
macsec-intf    Ethernet2
peer           10.255.0.6
peer-mode      slave
Status:
Data                     Value
------------------------ -----------------------------------
agent status             master
ip                       10.255.0.5
next key rotation event  14:10:25 11-Aug-2026
peer                     10.255.0.6
peer mode                slave
"""

SAMPLE_SLAVE_DAEMON = """
Agent: quadra (running with PID 2478)
Status:
Data                     Value
------------------------ -----------------------------------
agent status             slave
ip                       10.255.0.6
peer                     10.255.0.5
peer mode                master
"""

SAMPLE_MASTER_MACSEC = f"""
mac security
   profile {QUADRA_MACSEC_PROFILE_MASTER}
      cipher aes256-gcm-xpn
      key source sak static
         secure channel rx
            identifier {QUADRA_SC_RX_ID}
            an 1 key 7 0914480D1C0740110E5E51732F75706B
         secure channel tx
            identifier {QUADRA_SC_TX_ID}
            an 1 key 7 130411475E5F532F7E252C636720
"""

SAMPLE_SLAVE_MACSEC = f"""
mac security
   profile {QUADRA_MACSEC_PROFILE_SLAVE}
      cipher aes256-gcm-xpn
      key source sak static
         secure channel rx
            identifier {QUADRA_SC_TX_ID}
            an 1 key 7 094D485C4C5640175E0D007A7926
         secure channel tx
            identifier {QUADRA_SC_RX_ID}
            an 1 key 7 135D11160E0E53292E767D6A3173
"""

SAMPLE_PLAIN_MASTER_MACSEC = f"""
mac security
   profile {QUADRA_MACSEC_PROFILE_MASTER}
      cipher aes256-gcm-xpn
      key source sak static
         secure channel rx
            identifier {QUADRA_SC_RX_ID}
            an 0 key {QUADRA_KEY_RX}
         secure channel tx
            identifier {QUADRA_SC_TX_ID}
            an 0 key {QUADRA_KEY_TX}
"""

SAMPLE_PLAIN_SLAVE_MACSEC = f"""
mac security
   profile {QUADRA_MACSEC_PROFILE_SLAVE}
      cipher aes256-gcm-xpn
      key source sak static
         secure channel rx
            identifier {QUADRA_SC_TX_ID}
            an 0 key {QUADRA_KEY_TX}
         secure channel tx
            identifier {QUADRA_SC_RX_ID}
            an 0 key {QUADRA_KEY_RX}
"""

SAMPLE_MACSEC_INTERFACE_JSON = (
    '{"interfaces":{"Ethernet2":{"controlledPort":true,'
    '"keyMsgId":"static SAK: Rx AN: 1 Tx AN: 1","keyNum":0}}}'
)


def test_extension_installed_detects_installed_swix() -> None:
    output = "QuaDRA-1.0.10.rel1-aarch64.swix  1.0.10/1  A, I, B"
    assert extension_installed(output, "QuaDRA-1.0.10.rel1-aarch64.swix")


def test_extension_installed_false_when_not_installed() -> None:
    output = "QuaDRA-1.0.10.rel1-aarch64.swix  1.0.10/1  A"
    assert not extension_installed(output, "QuaDRA-1.0.10.rel1-aarch64.swix")


def test_parse_daemon_quadra_status_extracts_fields() -> None:
    status = parse_daemon_quadra_status(SAMPLE_MASTER_DAEMON)
    assert status["agent status"] == "master"
    assert status["next key rotation event"] == "14:10:25 11-Aug-2026"
    assert status["peer"] == "10.255.0.6"


def test_check_agent_role_accepts_master() -> None:
    status = check_agent_role(MASTER, SAMPLE_MASTER_DAEMON, expected_role="master")
    assert status["agent status"] == "master"


def test_check_agent_role_rejects_wrong_role() -> None:
    with pytest.raises(QkdCheckError, match="expected agent status 'slave'"):
        check_agent_role(MASTER, SAMPLE_MASTER_DAEMON, expected_role="slave")


def test_check_master_rotation_schedule() -> None:
    status = parse_daemon_quadra_status(SAMPLE_MASTER_DAEMON)
    check_master_rotation_schedule(MASTER, status)


def test_check_master_rotation_schedule_missing_next_event() -> None:
    status = parse_daemon_quadra_status(SAMPLE_SLAVE_DAEMON)
    with pytest.raises(QkdCheckError, match="missing next key rotation event"):
        check_master_rotation_schedule(MASTER, status)


def test_kme_key_request_lines_filters_post_requests() -> None:
    logs = (
        '::ffff:172.20.127.11 - - [11/Aug/2026 13:10:25] '
        '"POST /api/v1/keys/c565d5aa-8670-4446-8471-b0e53e315d2a/enc_keys HTTP/1.1" 200 -\n'
        '::ffff:172.20.127.13 - - [11/Aug/2026 13:10:25] '
        '"POST /api/v1/keys/25840139-0dd4-49ae-ba1e-b86731601803/dec_keys HTTP/1.1" 200 -\n'
    )
    enc = kme_key_request_lines(logs, "enc_keys", sae_id="c565d5aa-8670-4446-8471-b0e53e315d2a")
    dec = kme_key_request_lines(logs, "dec_keys", sae_id="25840139-0dd4-49ae-ba1e-b86731601803")
    assert len(enc) == 1
    assert len(dec) == 1


def test_check_kme_key_request_logs() -> None:
    import lab.test_macsec_qkd as mod

    sample = (
        '"POST /api/v1/keys/c565d5aa-8670-4446-8471-b0e53e315d2a/enc_keys HTTP/1.1" 200 -'
    )

    original = mod.read_docker_logs
    mod.read_docker_logs = lambda _container, verbose=None: sample  # type: ignore[assignment]
    try:
        line = check_kme_key_request_logs(
            "container",
            "kme-a",
            endpoint="enc_keys",
            sae_id="c565d5aa-8670-4446-8471-b0e53e315d2a",
            verbose=False,
        )
        assert "enc_keys" in line
    finally:
        mod.read_docker_logs = original


def test_parse_static_sak_profile_encrypted() -> None:
    master = parse_static_sak_profile(SAMPLE_MASTER_MACSEC, QUADRA_MACSEC_PROFILE_MASTER)
    slave = parse_static_sak_profile(SAMPLE_SLAVE_MACSEC, QUADRA_MACSEC_PROFILE_SLAVE)
    assert master.rx.encrypted
    assert master.rx.an == 1
    assert_static_sak_peer_mapping(master, slave)


def test_assert_plain_sak_key_exchange() -> None:
    master = parse_static_sak_profile(SAMPLE_PLAIN_MASTER_MACSEC, QUADRA_MACSEC_PROFILE_MASTER)
    slave = parse_static_sak_profile(SAMPLE_PLAIN_SLAVE_MACSEC, QUADRA_MACSEC_PROFILE_SLAVE)
    assert_static_sak_peer_mapping(master, slave)
    assert_plain_sak_key_exchange(master, slave)


def test_assert_plain_sak_key_exchange_rejects_mismatch() -> None:
    master = parse_static_sak_profile(SAMPLE_PLAIN_MASTER_MACSEC, QUADRA_MACSEC_PROFILE_MASTER)
    slave = parse_static_sak_profile(SAMPLE_PLAIN_SLAVE_MACSEC, QUADRA_MACSEC_PROFILE_SLAVE)
    slave_mismatch = parse_static_sak_profile(
        SAMPLE_PLAIN_SLAVE_MACSEC.replace(QUADRA_KEY_TX, "f" * len(QUADRA_KEY_TX)),
        QUADRA_MACSEC_PROFILE_SLAVE,
    )
    assert_static_sak_peer_mapping(master, slave_mismatch)
    with pytest.raises(QkdCheckError, match="plain SAK mismatch"):
        assert_plain_sak_key_exchange(master, slave_mismatch)


def test_find_rotation_success_log() -> None:
    logs = (
        "Aug 11 15:55:24 ceos3-qkd quadra-quadra: "
        "%QUADRA-4-ROTATION_SUCCESS: Successful QKD Macsec key rotation past agent startup or last failure"
    )

    class FakeCli:
        def __call__(self, _container: str, _commands: str, *, verbose: bool | None = None) -> str:
            return logs

    import lab.test_macsec_qkd as mod

    original = mod.ceos_cli
    mod.ceos_cli = FakeCli()  # type: ignore[assignment]
    try:
        line = find_rotation_success_log("container", "ceos3-qkd", verbose=False)
        assert line is not None
        assert "ROTATION_SUCCESS" in line
    finally:
        mod.ceos_cli = original


def test_note_rotation_success_log_warns_when_absent(capsys) -> None:
    import lab.test_macsec_qkd as mod

    original = mod.ceos_cli
    mod.ceos_cli = lambda *_a, **_k: "unrelated syslog line\n"  # type: ignore[assignment]
    try:
        found = note_rotation_success_log("container", "ceos3-qkd", verbose=False)
        assert found is False
    finally:
        mod.ceos_cli = original
    output = capsys.readouterr().out
    assert "WARN" in output
    assert "steady state" in output


def test_note_rotation_success_log_reports_when_present(capsys) -> None:
    logs = "%QUADRA-4-ROTATION_SUCCESS: Successful QKD Macsec key rotation"
    import lab.test_macsec_qkd as mod

    original = mod.ceos_cli
    mod.ceos_cli = lambda *_a, **_k: logs  # type: ignore[assignment]
    try:
        found = note_rotation_success_log("container", "ceos3-qkd", verbose=False)
        assert found is True
    finally:
        mod.ceos_cli = original
    output = capsys.readouterr().out
    assert "found rotation success" in output


def fake_qkd_cli(container: str, commands: str, *, installed=True, encrypted=True, **kwargs) -> str:
    slave = "ceos3-qkd" in container
    node = "ceos3-qkd" if slave else MASTER
    interface = QUADRA_MACSEC_INTF[node]
    profile = QUADRA_MACSEC_PROFILE_SLAVE if slave else QUADRA_MACSEC_PROFILE_MASTER
    if "show extensions" in commands:
        from lab.topology_contract import quadra_swix_name

        return f"{quadra_swix_name()}  1.0.10/1  A, I, B" if installed else ""
    if "show daemon quadra" in commands:
        assert installed, "daemon checks require the extension"
        return SAMPLE_SLAVE_DAEMON if slave else SAMPLE_MASTER_DAEMON
    if "show running-config interface" in commands:
        assert f"interface {interface}" in commands
        return f"interface {interface}\n   mac security profile {profile}\n"
    if "show running-config | section mac security" in commands:
        if encrypted:
            return SAMPLE_SLAVE_MACSEC if slave else SAMPLE_MASTER_MACSEC
        return SAMPLE_PLAIN_SLAVE_MACSEC if slave else SAMPLE_PLAIN_MASTER_MACSEC
    if "show mac security interface" in commands:
        assert f"interface {interface}" in commands
        an = 1 if encrypted else 0
        return json.dumps({"interfaces": {interface: {
            "controlledPort": True,
            "keyMsgId": f"static SAK: Rx AN: {an} Tx AN: {an}",
            "keyNum": 0,
        }}})
    if "show logging" in commands:
        assert installed, "rotation log checks require the extension"
        return "%QUADRA-4-ROTATION_SUCCESS: Successful QKD Macsec key rotation"
    if "ping " in commands:
        peer = "10.255.0.5" if slave else "10.255.0.6"
        assert f"ping {peer}" in commands
        return "Success rate is 100 percent"
    raise AssertionError(commands)


@pytest.mark.parametrize("installed", [False, True])
@pytest.mark.parametrize("encrypted", [False, True])
def test_run_qkd_checks_happy_path(capsys, monkeypatch, installed, encrypted) -> None:
    import lab.test_macsec_qkd as mod

    cli = Mock(side_effect=lambda c, cmd, **kw: fake_qkd_cli(
        c, cmd, installed=installed, encrypted=encrypted, **kw,
    ))
    logs = Mock(side_effect=lambda container, **kw: (
        '\"POST /api/v1/keys/c565d5aa-8670-4446-8471-b0e53e315d2a/enc_keys HTTP/1.1\" 200 -'
        if "kme-a" in container
        else '\"POST /api/v1/keys/25840139-0dd4-49ae-ba1e-b86731601803/dec_keys HTTP/1.1\" 200 -'
    ))
    monkeypatch.setattr(mod, "ceos_cli", cli)
    monkeypatch.setattr(mod, "ceos_show_json", lambda c, cmd, **kw: json.loads(cli(c, cmd, **kw)))
    monkeypatch.setattr(mod, "read_docker_logs", logs)
    ran = run_qkd_checks(clab_name="quantum-safe", verbose=False)
    assert ran is installed
    assert logs.call_count == (2 if installed else 0)
    output = capsys.readouterr().out
    assert "QuaDRA: ✓" in output
    assert "static SAK profile quadra-master on Ethernet2" in output
    assert "static SAK profile quadra-slave on Ethernet1" in output
    assert output.count("MACsec controlled port up") == 2
    assert output.count("ping 10.255.0.") == 2
    assert "SC/AN mapping OK" in output
    if not installed:
        assert "8 passed, 1 skipped" in output
        assert "daemon and KME checks skipped" in output
        assert not any("show daemon quadra" in call.args[1] for call in cli.call_args_list)
    # Each direction has one final connectivity probe, plus convergence pings.
    assert sum("repeat 3" in call.args[1] for call in cli.call_args_list) == 2


@pytest.mark.parametrize("failure", ["binding", "port", "key_mapping", "ping"])
def test_static_macsec_failures_are_not_skipped_without_extension(monkeypatch, failure) -> None:
    import lab.test_macsec_qkd as mod

    def cli(container, commands, **kwargs):
        result = fake_qkd_cli(container, commands, installed=False, encrypted=False)
        if failure == "binding" and "show running-config interface" in commands:
            return "interface Ethernet2\n"
        if failure == "port" and "show mac security interface" in commands:
            return '{"controlledPort":false}'
        if failure == "key_mapping" and "ceos3-qkd" in container:
            return result.replace(QUADRA_KEY_TX, "f" * len(QUADRA_KEY_TX))
        if failure == "ping" and "repeat 3" in commands:
            return "Success rate is 0 percent"
        return result

    monkeypatch.setattr(mod, "ceos_cli", cli)
    monkeypatch.setattr(mod, "ceos_show_json", lambda c, cmd, **kw: json.loads(cli(c, cmd, **kw)))
    monkeypatch.setattr(mod.time, "sleep", Mock())
    with pytest.raises(QkdCheckError):
        run_qkd_checks(clab_name="quantum-safe", verbose=False)


@pytest.mark.parametrize("converges", [False, True])
def test_static_macsec_convergence_retries_are_bounded(monkeypatch, converges) -> None:
    import lab.test_macsec_qkd as mod

    states = [{"controlledPort": False}] * (STATIC_MACSEC_POLL_ATTEMPTS - 1)
    states.append(json.loads(SAMPLE_MACSEC_INTERFACE_JSON) if converges else {"controlledPort": True})
    show = Mock(side_effect=states)
    sleep = Mock()
    monkeypatch.setattr(mod, "ceos_cli", Mock())
    monkeypatch.setattr(mod, "ceos_show_json", show)
    monkeypatch.setattr(mod.time, "sleep", sleep)
    if converges:
        check_static_macsec_interface("master", MASTER, "Ethernet2")
    else:
        with pytest.raises(QkdCheckError, match="active static SAK"):
            check_static_macsec_interface("master", MASTER, "Ethernet2")
    assert show.call_count == STATIC_MACSEC_POLL_ATTEMPTS
    assert sleep.call_count == STATIC_MACSEC_POLL_ATTEMPTS - 1
    assert all(call.args == (STATIC_MACSEC_POLL_INTERVAL_SEC,) for call in sleep.call_args_list)
