"""Unit tests for OpenConfig gRPC live check helpers."""

from __future__ import annotations

from lab.test_openconfig_grpc import gnpsi_supported_on_ceos


class _FakeTargets:
    clab_name = "quantum-safe"

    def ceos_container(self, node: str) -> str:
        return f"arista-quantum-safe-{node}"

    def ceos_mgmt_ip(self, node: str, family: str) -> str:
        return "172.20.127.11"


def test_gnpsi_supported_detects_invalid_command(monkeypatch) -> None:
    def fake_cli(container: str, commands: str, *, verbose=None) -> str:
        return "% Invalid input\n"

    monkeypatch.setattr("lab.test_pqc_connections.ceos_cli", fake_cli)
    assert gnpsi_supported_on_ceos(_FakeTargets(), "ceos1-both") is False


def test_gnpsi_supported_accepts_running_transport(monkeypatch) -> None:
    def fake_cli(container: str, commands: str, *, verbose=None) -> str:
        return "Enabled: Yes\nServer: running on port 6031, in MGMT VRF\n"

    monkeypatch.setattr("lab.test_pqc_connections.ceos_cli", fake_cli)
    assert gnpsi_supported_on_ceos(_FakeTargets(), "ceos1-both") is True
