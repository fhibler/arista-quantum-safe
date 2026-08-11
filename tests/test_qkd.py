"""Unit tests for QuaDRA / QKD live check helpers."""

from __future__ import annotations

import pytest

from lab.test_qkd import (
    MASTER,
    QkdCheckError,
    assert_plain_sak_key_exchange,
    assert_static_sak_peer_mapping,
    check_agent_role,
    check_kme_key_request_logs,
    check_master_rotation_schedule,
    find_rotation_success_log,
    note_rotation_success_log,
    check_static_sak_key_sync,
    extension_installed,
    kme_key_request_lines,
    parse_daemon_quadra_status,
    parse_static_sak_profile,
    run_qkd_checks,
)
from lab.topology_contract import (
    QUADRA_KEY_RX,
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
    import lab.test_qkd as mod

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

    import lab.test_qkd as mod

    original = mod.ceos_cli
    mod.ceos_cli = FakeCli()  # type: ignore[assignment]
    try:
        line = find_rotation_success_log("container", "ceos3-qkd", verbose=False)
        assert line is not None
        assert "ROTATION_SUCCESS" in line
    finally:
        mod.ceos_cli = original


def test_note_rotation_success_log_warns_when_absent(capsys) -> None:
    import lab.test_qkd as mod

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
    import lab.test_qkd as mod

    original = mod.ceos_cli
    mod.ceos_cli = lambda *_a, **_k: logs  # type: ignore[assignment]
    try:
        found = note_rotation_success_log("container", "ceos3-qkd", verbose=False)
        assert found is True
    finally:
        mod.ceos_cli = original
    output = capsys.readouterr().out
    assert "found rotation success" in output


def test_run_qkd_checks_skips_when_extension_missing(capsys) -> None:
    import lab.test_qkd as mod
    from unittest.mock import patch

    with patch.object(mod, "quadra_installed_on_nodes", return_value=False):
        ran = run_qkd_checks(clab_name="quantum-safe", verbose=False)
    assert ran is False
    output = capsys.readouterr().out
    assert "skipped" in output.lower()


def test_run_qkd_checks_happy_path(capsys) -> None:
    import lab.test_qkd as mod
    from unittest.mock import patch

    def fake_cli(container: str, commands: str, *, verbose: bool | None = None) -> str:
        if "show extensions" in commands:
            return "QuaDRA-1.0.10.rel1-aarch64.swix  1.0.10/1  A, I, B"
        if "show daemon quadra" in commands:
            if "ceos3-qkd" in container:
                return SAMPLE_SLAVE_DAEMON
            return SAMPLE_MASTER_DAEMON
        if "show running-config | section mac security" in commands:
            if "ceos3-qkd" in container:
                return SAMPLE_SLAVE_MACSEC
            return SAMPLE_MASTER_MACSEC
        if "show mac security interface" in commands:
            return SAMPLE_MACSEC_INTERFACE_JSON
        if "show logging" in commands:
            return "%QUADRA-4-ROTATION_SUCCESS: Successful QKD Macsec key rotation"
        if "ping " in commands:
            return "Success rate is 100 percent"
        raise AssertionError(commands)

    with (
        patch.object(mod, "quadra_installed_on_nodes", return_value=True),
        patch.object(mod, "ceos_cli", side_effect=fake_cli),
        patch(
            "lab.test_pqc_connections.ceos_show_json",
            side_effect=lambda _c, _cmd, verbose=None: __import__("json").loads(
                SAMPLE_MACSEC_INTERFACE_JSON
            ),
        ),
        patch.object(
            mod,
            "read_docker_logs",
            side_effect=lambda container, verbose=None: (
                '"POST /api/v1/keys/c565d5aa-8670-4446-8471-b0e53e315d2a/enc_keys HTTP/1.1" 200 -'
                if "kme-a" in container
                else '"POST /api/v1/keys/25840139-0dd4-49ae-ba1e-b86731601803/dec_keys HTTP/1.1" 200 -'
            ),
        ),
    ):
        ran = run_qkd_checks(clab_name="quantum-safe", verbose=False)
    assert ran is True
    output = capsys.readouterr().out
    assert "QuaDRA: ✓" in output
