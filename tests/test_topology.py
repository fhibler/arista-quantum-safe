import subprocess

import pytest

from lab.topology_contract import (
    CEOS_DATA_PLANE,
    CEOS_IMAGE_PLACEHOLDER,
    CEOS_STARTUP_CONFIGS,
    DEFAULT_CEOS_IMAGE,
    HOST_DATA_PLANE,
    MGMT_SUBNET_PLACEHOLDER,
    RADIUS_BINDS,
    REPO_ROOT,
    load_topology,
    resolve_topo_path,
    validate_host_data_plane,
    validate_topology,
)
from tests.scaffold_contract import REPO_ROOT as SCAFFOLD_ROOT


@pytest.fixture(autouse=True)
def ensure_generated_topo() -> None:
    subprocess.run(["make", "gen-topo"], cwd=SCAFFOLD_ROOT, check=True, capture_output=True)


@pytest.fixture
def topology() -> dict:
    return load_topology()


@pytest.fixture
def generated_topology() -> dict:
    from lab.topology_contract import GEN_TOPOLOGY_PATH

    return load_topology(GEN_TOPOLOGY_PATH)


def test_topology_yaml_parses(topology: dict) -> None:
    assert topology["name"] == "qkd-macsec-radius"


def test_topology_template_placeholders(topology: dict) -> None:
    assert topology["mgmt"]["ipv4-subnet"] == MGMT_SUBNET_PLACEHOLDER
    assert topology["topology"]["kinds"]["arista_ceos"]["image"] == CEOS_IMAGE_PLACEHOLDER
    assert topology["topology"]["nodes"]["ceos1"]["mgmt-ipv4"] == "${MGMT_IP_CEOS1}"


def test_generated_topology_contract(generated_topology: dict) -> None:
    errors = validate_topology(generated_topology)
    assert errors == [], "\n".join(errors)


def test_validate_topology_accepts_ceos_image_override(generated_topology: dict) -> None:
    custom = "ceos:5.0.0F"
    data = {**generated_topology, "topology": {**generated_topology["topology"]}}
    data["topology"]["kinds"] = {
        **generated_topology["topology"]["kinds"],
        "arista_ceos": {
            **generated_topology["topology"]["kinds"]["arista_ceos"],
            "image": custom,
        },
    }
    assert validate_topology(data, ceos_image=custom) == []
    assert validate_topology(data) != []


def test_ceos_image_placeholder(topology: dict) -> None:
    image = topology["topology"]["kinds"]["arista_ceos"]["image"]
    assert image == CEOS_IMAGE_PLACEHOLDER


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
def test_ceos_startup_config_paths(generated_topology: dict, ceos: str, spec: dict) -> None:
    startup = generated_topology["topology"]["nodes"][ceos]["startup-config"]
    assert startup == CEOS_STARTUP_CONFIGS[ceos]
    path = resolve_topo_path(startup, REPO_ROOT / "lab")
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert spec["eth1"] in text
    assert spec["eth2"] in text
