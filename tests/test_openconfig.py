"""Unit tests for OpenConfig live check runner."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from lab.test_openconfig import run_openconfig_checks
from lab.test_pqc_connections import PQC_GROUP
from tests.test_pqc_connections import _pqc_config_json


def test_run_openconfig_checks_smoke(capsys) -> None:
    config_json = _pqc_config_json()

    def fake_ceos_cli(_container: str, commands: str, **kwargs: object) -> str:
        if "show running-config | section eos-sdk-rpc" in commands:
            return "management api eos-sdk-rpc\n   transport grpc default\n      ssl profile GNMI\n"
        if "| json" in commands:
            return __import__("json").dumps(config_json)
        raise AssertionError(f"unexpected ceos_cli commands: {commands!r}")

    def fake_openssl_s_client(**kwargs: object) -> str:
        return (
            f"CONNECTION ESTABLISHED\nProtocol version: TLSv1.3\n"
            f"Negotiated TLS1.3 group: {PQC_GROUP}\n"
        )

    def fake_run_gnmi_get(*, node: str, **kwargs: object):
        _ = kwargs
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=f'[{{"values":{{"system/config/hostname":"{node}"}}}}]',
            stderr="",
        )

    with (
        patch("lab.test_pqc_connections.ceos_cli", side_effect=fake_ceos_cli),
        patch("lab.tls_wire.run_openssl_s_client", side_effect=fake_openssl_s_client),
        patch("lab.test_pqc_connections.run_gnmi_get", side_effect=fake_run_gnmi_get),
        patch("lab.test_openconfig.run_openconfig_grpc_checks"),
    ):
        run_openconfig_checks(clab_name="quantum-safe", mgmt_subnet="172.20.127.0/24")

    output = capsys.readouterr().out
    assert "OpenConfig verification" in output
    assert "=== ceos1-both ===" in output
    assert "--- gNMI ---" in output
    assert "OpenConfig: ✓" in output
