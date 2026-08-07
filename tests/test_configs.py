"""Tests for configuration artifacts (RADIUS + cEOS)."""

from pathlib import Path

import pytest

from lab.render_topo import render_lab
from lab.topology_contract import (
    CEOS_DATA_PLANE,
    CONFIG_PATHS,
    DEFAULT_MGMT_SUBNET,
    HOST_DATA_PLANE,
    MGMT_IPS,
    RADIUS_SECRET,
    RADIUS_SERVER_IP,
    validate_ceos_configs,
    validate_radius_configs,
)


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def rendered_configs(repo_root: Path) -> None:
    render_lab(repo_root=repo_root)


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
def test_ceos_no_todo_stub_markers(repo_root: Path, ceos: str, spec: dict) -> None:
    text = (repo_root / "lab" / ".gen" / f"{ceos}.cfg").read_text(encoding="utf-8")
    assert "TODO:" not in text
    assert f"hostname {ceos}" in text
    assert spec["mgmt_ip"] in text


def test_clients_conf_ceos_entries(repo_root: Path) -> None:
    clients = (repo_root / "lab" / ".gen" / "clients.conf").read_text(encoding="utf-8")
    assert RADIUS_SECRET in clients
    assert MGMT_IPS["ceos1"] in clients
    assert MGMT_IPS["ceos2"] in clients


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
    assert RADIUS_SERVER_IP == MGMT_IPS["radius"]


def test_custom_mgmt_subnet_render(repo_root: Path) -> None:
    custom = "192.168.28.0/24"
    render_lab(repo_root=repo_root, mgmt_subnet=custom)
    errors = validate_ceos_configs(repo_root, mgmt_subnet=custom)
    assert errors == [], "\n".join(errors)
    text = (repo_root / "lab" / ".gen" / "ceos1.cfg").read_text(encoding="utf-8")
    assert "192.168.28.11/24" in text
    assert "192.168.28.1" in text
