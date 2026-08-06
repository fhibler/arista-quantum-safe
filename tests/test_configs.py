"""Tests for Session 2 configuration artifacts (RADIUS + cEOS)."""

from pathlib import Path

import pytest

from lab.topology_contract import (
    CEOS_DATA_PLANE,
    CONFIG_PATHS,
    HOST_DATA_PLANE,
    RADIUS_SECRET,
    RADIUS_SERVER_IP,
    validate_ceos_configs,
    validate_radius_configs,
)


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_config_paths_exist() -> None:
    for name, path in CONFIG_PATHS.items():
        assert path.is_file(), f"missing config path for {name}: {path}"


def test_ceos_configs_contract(repo_root: Path) -> None:
    errors = validate_ceos_configs(repo_root)
    assert errors == [], "\n".join(errors)


def test_radius_configs_contract(repo_root: Path) -> None:
    errors = validate_radius_configs(repo_root)
    assert errors == [], "\n".join(errors)


@pytest.mark.parametrize("ceos,spec", CEOS_DATA_PLANE.items())
def test_ceos_no_session_stub_markers(repo_root: Path, ceos: str, spec: dict) -> None:
    text = (repo_root / "configs" / "ceos" / f"{ceos}.cfg").read_text(encoding="utf-8")
    assert "TODO Session" not in text
    assert f"hostname {ceos}" in text
    assert spec["mgmt_ip"] in text


def test_clients_conf_ceos_entries(repo_root: Path) -> None:
    clients = (repo_root / "configs" / "radius" / "raddb" / "clients.conf").read_text(
        encoding="utf-8"
    )
    assert RADIUS_SECRET in clients
    assert "192.168.127.11" in clients
    assert "192.168.127.12" in clients


def test_radiusd_conf_logs_to_bind_mount(repo_root: Path) -> None:
    radiusd = (repo_root / "configs" / "radius" / "raddb" / "radiusd.conf").read_text(
        encoding="utf-8"
    )
    assert "destination = files" in radiusd
    assert "file = /var/log/radius/radius.log" in radiusd


def test_authorize_accepts_lab_auth(repo_root: Path) -> None:
    authorize = (
        repo_root / "configs" / "radius" / "raddb" / "mods-config" / "files" / "authorize"
    ).read_text(encoding="utf-8")
    assert "DEFAULT Auth-Type := Accept" in authorize


def test_data_plane_constants_match_host_exec() -> None:
    """Document-level sanity: host gateways are switch eth2 addresses."""
    assert HOST_DATA_PLANE["host1"]["gateway"] == CEOS_DATA_PLANE["ceos1"]["eth2"].split("/")[0]
    assert HOST_DATA_PLANE["host2"]["gateway"] == CEOS_DATA_PLANE["ceos2"]["eth2"].split("/")[0]
    assert RADIUS_SERVER_IP == "192.168.127.50"
