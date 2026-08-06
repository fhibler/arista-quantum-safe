from pathlib import Path

import pytest

from lab.topology_contract import (
    CEOS_DATA_PLANE,
    DEFAULT_CEOS_IMAGE,
    HOST_DATA_PLANE,
    MGMT_IPS,
    RADIUS_BINDS,
    load_topology,
    validate_host_data_plane,
    validate_topology,
)


@pytest.fixture
def topology() -> dict:
    return load_topology()


def test_topology_yaml_parses(topology: dict) -> None:
    assert topology["name"] == "qkd-macsec-radius"


def test_topology_contract(topology: dict) -> None:
    errors = validate_topology(topology)
    assert errors == [], "\n".join(errors)


def test_validate_topology_accepts_ceos_image_override(topology: dict) -> None:
    custom = "ceos:5.0.0F"
    data = {**topology, "topology": {**topology["topology"]}}
    data["topology"]["kinds"] = {
        **topology["topology"]["kinds"],
        "arista_ceos": {
            **topology["topology"]["kinds"]["arista_ceos"],
            "image": custom,
        },
    }
    assert validate_topology(data, ceos_image=custom) == []
    assert validate_topology(data) != []


def test_ceos_image_placeholder(topology: dict) -> None:
    image = topology["topology"]["kinds"]["arista_ceos"]["image"]
    assert image == DEFAULT_CEOS_IMAGE


@pytest.mark.parametrize("node,expected_ip", MGMT_IPS.items())
def test_mgmt_ips(topology: dict, node: str, expected_ip: str) -> None:
    assert topology["topology"]["nodes"][node]["mgmt-ipv4"] == expected_ip


@pytest.mark.parametrize("expected_bind", RADIUS_BINDS)
def test_radius_bind_mounts(topology: dict, expected_bind: str) -> None:
    binds = topology["topology"]["nodes"]["radius"]["binds"]
    assert expected_bind in binds


@pytest.mark.parametrize("host,spec", HOST_DATA_PLANE.items())
def test_host_data_plane_exec(topology: dict, host: str, spec: dict) -> None:
    nodes = topology["topology"]["nodes"]
    errors = validate_host_data_plane(nodes)
    host_errors = [e for e in errors if e.startswith(f"{host} ")]
    assert host_errors == [], "\n".join(host_errors)
    exec_text = "\n".join(nodes[host]["exec"])
    assert spec["addr"] in exec_text
    assert spec["gateway"] in exec_text


@pytest.mark.parametrize("ceos,spec", CEOS_DATA_PLANE.items())
def test_ceos_startup_config_paths(topology: dict, ceos: str, spec: dict) -> None:
    startup = topology["topology"]["nodes"][ceos]["startup-config"]
    assert startup == f"configs/ceos/{ceos}.cfg"
    path = Path(__file__).resolve().parents[1] / startup
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert spec["eth1"] in text
    assert spec["eth2"] in text
