import subprocess

import pytest

from lab.topology_contract import (
    CEOS_DATA_PLANE,
    CEOS_IMAGE_PLACEHOLDER,
    CEOS_STARTUP_CONFIGS,
    DEFAULT_CEOS_IMAGE,
    HOST_DATA_PLANE,
    KME_A_PORT,
    KME_B_PORT,
    KME_BINDS,
    KME_IMAGE,
    KME_NODES,
    MGMT_SUBNET_PLACEHOLDER,
    RADIUS_BINDS,
    REPO_ROOT,
    kme_other_kmes,
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


@pytest.mark.parametrize(
    "node,expected_bind",
    [("kme-a", b) for b in KME_BINDS] + [("kme-b", b) for b in KME_BINDS],
)
def test_kme_bind_mounts(topology: dict, node: str, expected_bind: str) -> None:
    binds = topology["topology"]["nodes"][node]["binds"]
    assert expected_bind in binds


def test_kme_a_radius_attached(topology: dict) -> None:
    kme_a = topology["topology"]["nodes"]["kme-a"]
    assert kme_a["image"] == KME_IMAGE
    assert kme_a["mgmt-ipv4"] == "${MGMT_IP_KME_A}"
    assert "NET_ADMIN" in kme_a["cap-add"]
    assert kme_a["env"]["OTHER_KMES"] == "https://${MGMT_IP_KME_B}:8020"
    assert kme_a["env"]["RADIUS_IP"] == "${MGMT_IP_RADIUS}"
    assert kme_a["env"]["PORT"] == str(KME_A_PORT)


def test_kme_b_peer_linked(topology: dict) -> None:
    kme_b = topology["topology"]["nodes"]["kme-b"]
    assert kme_b["image"] == KME_IMAGE
    assert kme_b["mgmt-ipv4"] == "${MGMT_IP_KME_B}"
    assert "NET_ADMIN" in kme_b["cap-add"]
    assert kme_b["env"]["OTHER_KMES"] == "https://${MGMT_IP_KME_A}:8010"
    assert kme_b["env"]["PORT"] == str(KME_B_PORT)
    assert kme_b["env"]["RADIUS_IP"] == "${MGMT_IP_RADIUS}"
    assert kme_b["env"]["SAE_CERT"] == "/certs/sae-b.crt.pem"
    assert kme_b["env"]["KME_ID"] == KME_NODES["kme-b"]["kme_id"]


def test_kme_peer_urls_match_contract(generated_topology: dict) -> None:
    from lab.topology_contract import MGMT_IPS

    kme_a = generated_topology["topology"]["nodes"]["kme-a"]
    kme_b = generated_topology["topology"]["nodes"]["kme-b"]
    assert kme_a["env"]["OTHER_KMES"] == kme_other_kmes(MGMT_IPS["kme-b"], KME_B_PORT)
    assert kme_b["env"]["OTHER_KMES"] == kme_other_kmes(MGMT_IPS["kme-a"], KME_A_PORT)


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
