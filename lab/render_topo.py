"""Render topology and mgmt-dependent configs from templates."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

import yaml

from lab.gen_kme_pki import generate_kme_pki
from lab.gen_pki import generate_radsec_pki
from lab.topology_contract import (
    DEFAULT_CEOS_IMAGE,
    DEFAULT_MGMT_IPV6_SUBNET,
    DEFAULT_MGMT_SUBNET,
    CEOS_QUADRA_NODES,
    GEN_TOPOLOGY_ANNOTATIONS_PATH,
    GEN_TOPOLOGY_PATH,
    KME_A_PORT,
    KME_B_PORT,
    KME_B_SAE_ID,
    KME_KEY_SIZE,
    KME_SAE_CLIENT_NODES,
    KME_SAE_ID,
    QUADRA_KEY_RX,
    QUADRA_KEY_TX,
    QUADRA_MACSEC_PROFILE_MASTER,
    QUADRA_MACSEC_PROFILE_SLAVE,
    QUADRA_MACSEC_INTF,
    QUADRA_SC_RX_ID,
    QUADRA_SC_TX_ID,
    quadra_swix_clab_bind,
    quadra_swix_install_exec,
    TOPOLOGY_ANNOTATIONS_PATH,
    TOPOLOGY_PATH,
    mgmt_gateway,
    mgmt_ips_for_subnet,
    mgmt_ipv6_gateway,
    mgmt_ipv6_ips_for_subnet,
    mgmt_ipv6_prefix_len,
    mgmt_prefix_len,
)

QUADRA_TEMPLATE_PATHS = {
    "quadra-macsec-master": Path("configs/ceos/quadra-macsec-master.cfg.in"),
    "quadra-macsec-slave": Path("configs/ceos/quadra-macsec-slave.cfg.in"),
    "quadra-daemon-master": Path("configs/ceos/quadra-daemon-master.cfg.in"),
    "quadra-daemon-slave": Path("configs/ceos/quadra-daemon-slave.cfg.in"),
}

TEMPLATE_PATHS = {
    "ceos1-both.cfg": Path("configs/ceos/ceos1-both.cfg.in"),
    "ceos2-pqc.cfg": Path("configs/ceos/ceos2-pqc.cfg.in"),
    "ceos3-qkd.cfg": Path("configs/ceos/ceos3-qkd.cfg.in"),
    "clients.conf": Path("configs/radius/raddb/clients.conf.in"),
    "clients-radsec.conf": Path("configs/radius/raddb/clients-radsec.conf.in"),
}


def build_substitutions(
    *,
    repo_root: Path,
    ceos_image: str,
    mgmt_subnet: str,
    mgmt_ipv6_subnet: str = DEFAULT_MGMT_IPV6_SUBNET,
) -> dict[str, str]:
    ips = mgmt_ips_for_subnet(mgmt_subnet)
    ips6 = mgmt_ipv6_ips_for_subnet(mgmt_ipv6_subnet)
    control_plane_acl = (repo_root / "configs/ceos/control-plane-acl.cfg.in").read_text(
        encoding="utf-8",
    )
    quadra_base = {
        "KME_A_PORT": str(KME_A_PORT),
        "KME_B_PORT": str(KME_B_PORT),
        "KME_SAE_ID": KME_SAE_ID,
        "KME_B_SAE_ID": KME_B_SAE_ID,
        "QUADRA_KEY_RX": QUADRA_KEY_RX,
        "QUADRA_KEY_TX": QUADRA_KEY_TX,
        "QUADRA_SC_RX_ID": QUADRA_SC_RX_ID,
        "QUADRA_SC_TX_ID": QUADRA_SC_TX_ID,
        "MGMT_IP_KME_A": ips["kme-a"],
        "MGMT_IP_KME_B": ips["kme-b"],
    }
    quadra_master_ctx = {
        **quadra_base,
        "QUADRA_MACSEC_PROFILE": QUADRA_MACSEC_PROFILE_MASTER,
        "QUADRA_MACSEC_INTF": QUADRA_MACSEC_INTF["ceos1-both"],
        "QUADRA_PEER_IP": "10.255.0.6",
    }
    quadra_slave_ctx = {
        **quadra_base,
        "QUADRA_MACSEC_PROFILE": QUADRA_MACSEC_PROFILE_SLAVE,
        "QUADRA_MACSEC_INTF": "Ethernet1",
        "QUADRA_PEER_IP": "10.255.0.5",
    }

    def render_quadra(name: str, ctx: dict[str, str]) -> str:
        path = repo_root / QUADRA_TEMPLATE_PATHS[name]
        return substitute_placeholders(path.read_text(encoding="utf-8"), ctx).rstrip("\n")

    return {
        "CEOS_IMAGE": ceos_image,
        "MGMT_SUBNET": mgmt_subnet,
        "MGMT_GATEWAY": mgmt_gateway(mgmt_subnet),
        "MGMT_PREFIX": str(mgmt_prefix_len(mgmt_subnet)),
        "MGMT_IPV6_SUBNET": mgmt_ipv6_subnet,
        "MGMT_IPV6_GATEWAY": mgmt_ipv6_gateway(mgmt_ipv6_subnet),
        "MGMT_IPV6_PREFIX": str(mgmt_ipv6_prefix_len(mgmt_ipv6_subnet)),
        "MGMT_IP_CEOS1_BOTH": ips["ceos1-both"],
        "MGMT_IP_CEOS2_PQC": ips["ceos2-pqc"],
        "MGMT_IP_CEOS3_QKD": ips["ceos3-qkd"],
        "MGMT_IP_HOST1": ips["host1"],
        "MGMT_IP_HOST2": ips["host2"],
        "MGMT_IP_HOST3": ips["host3"],
        "MGMT_IP_RADIUS": ips["radius"],
        "MGMT_IP_SYSLOG": ips["syslog"],
        "MGMT_IP_KME_A": ips["kme-a"],
        "MGMT_IP_KME_B": ips["kme-b"],
        "MGMT_IPV6_CEOS1_BOTH": ips6["ceos1-both"],
        "MGMT_IPV6_CEOS2_PQC": ips6["ceos2-pqc"],
        "MGMT_IPV6_CEOS3_QKD": ips6["ceos3-qkd"],
        "MGMT_IPV6_HOST1": ips6["host1"],
        "MGMT_IPV6_HOST2": ips6["host2"],
        "MGMT_IPV6_HOST3": ips6["host3"],
        "MGMT_IPV6_RADIUS": ips6["radius"],
        "MGMT_IPV6_SYSLOG": ips6["syslog"],
        "MGMT_IPV6_KME_A": ips6["kme-a"],
        "MGMT_IPV6_KME_B": ips6["kme-b"],
        "KME_SAE_CLIENT_IPS": ",".join(
            [ips[node] for node in KME_SAE_CLIENT_NODES]
            + [ips6[node] for node in KME_SAE_CLIENT_NODES]
        ),
        "RADIUS_SERVER_IP": ips6["radius"],
        "SYSLOG_SERVER_IPV4": ips["syslog"],
        "SYSLOG_SERVER_IPV6": ips6["syslog"],
        "CONTROL_PLANE_ACL": control_plane_acl.rstrip("\n"),
        "QUADRA_MACSEC_MASTER": render_quadra("quadra-macsec-master", quadra_master_ctx),
        "QUADRA_MACSEC_SLAVE": render_quadra("quadra-macsec-slave", quadra_slave_ctx),
        "QUADRA_DAEMON_MASTER": render_quadra("quadra-daemon-master", quadra_master_ctx),
        "QUADRA_DAEMON_SLAVE": render_quadra("quadra-daemon-slave", quadra_slave_ctx),
    }


def inject_quadra_clab_nodes(topology: dict) -> None:
    """Append QuaDRA bind mounts and install exec when the host swix is present."""
    bind = quadra_swix_clab_bind()
    exec_cmd = quadra_swix_install_exec()
    if bind is None or exec_cmd is None:
        return
    nodes = topology["topology"]["nodes"]
    for node in CEOS_QUADRA_NODES:
        nodes[node]["binds"].append(bind)
        nodes[node]["exec"].append(exec_cmd)


def substitute_placeholders(content: str, substitutions: dict[str, str]) -> str:
    rendered = content
    for key, value in substitutions.items():
        rendered = rendered.replace(f"${{{key}}}", value)
    if re.search(r"\$\{[A-Z0-9_]+\}", rendered):
        unresolved = sorted(set(re.findall(r"\$\{([A-Z0-9_]+)\}", rendered)))
        raise ValueError(f"unresolved template placeholders: {', '.join(unresolved)}")
    return rendered


def render_topology(
    *,
    repo_root: Path,
    ceos_image: str,
    mgmt_subnet: str,
    src: Path | None = None,
    dst: Path | None = None,
) -> Path:
    substitutions = build_substitutions(
        repo_root=repo_root,
        ceos_image=ceos_image,
        mgmt_subnet=mgmt_subnet,
    )
    topo_src = src or (repo_root / TOPOLOGY_PATH.relative_to(repo_root))
    topo_dst = dst or (repo_root / GEN_TOPOLOGY_PATH.relative_to(repo_root))
    content = topo_src.read_text(encoding="utf-8")
    rendered = substitute_placeholders(content, substitutions)
    topology = yaml.safe_load(rendered)
    inject_quadra_clab_nodes(topology)
    topo_dst.write_text(yaml.dump(topology, sort_keys=False), encoding="utf-8")
    return topo_dst


def render_topology_annotations(
    *,
    repo_root: Path,
    src: Path | None = None,
    dst: Path | None = None,
) -> Path:
    ann_src = src or (repo_root / TOPOLOGY_ANNOTATIONS_PATH.relative_to(repo_root))
    ann_dst = dst or (repo_root / GEN_TOPOLOGY_ANNOTATIONS_PATH.relative_to(repo_root))
    if not ann_src.is_file():
        raise FileNotFoundError(ann_src)
    shutil.copyfile(ann_src, ann_dst)
    return ann_dst


def render_config_templates(*, repo_root: Path, mgmt_subnet: str, ceos_image: str) -> None:
    substitutions = build_substitutions(
        repo_root=repo_root,
        ceos_image=ceos_image,
        mgmt_subnet=mgmt_subnet,
    )
    out_dir = repo_root / "lab" / ".gen"
    out_dir.mkdir(parents=True, exist_ok=True)

    for output_name, template_rel in TEMPLATE_PATHS.items():
        template_path = repo_root / template_rel
        if not template_path.is_file():
            raise FileNotFoundError(template_path)
        rendered = substitute_placeholders(template_path.read_text(encoding="utf-8"), substitutions)
        (out_dir / output_name).write_text(rendered, encoding="utf-8")


def render_kme_lab_conf(*, repo_root: Path, mgmt_subnet: str) -> Path:
    """Write lab SAE client settings for offline/CLI KME checks (not used by FreeRADIUS)."""
    ips = mgmt_ips_for_subnet(mgmt_subnet)
    pki = repo_root / "lab" / ".gen" / "kme-pki"
    lines = [
        "# Generated by make gen-topo — ETSI QKD 014 endpoints for lab SAE client",
        f"KME_A_HOST={ips['kme-a']}",
        f"KME_A_PORT={KME_A_PORT}",
        f"KME_B_HOST={ips['kme-b']}",
        f"KME_B_PORT={KME_B_PORT}",
        f"MASTER_SAE_ID={KME_SAE_ID}",
        f"SLAVE_SAE_ID={KME_B_SAE_ID}",
        f"KEY_SIZE={KME_KEY_SIZE}",
        f"MASTER_CERT={pki / 'sae.crt.pem'}",
        f"MASTER_KEY={pki / 'sae.key.pem'}",
        f"SLAVE_CERT={pki / 'sae-b.crt.pem'}",
        f"SLAVE_KEY={pki / 'sae-b.key.pem'}",
        f"CA_CERT={pki / 'ca.crt.pem'}",
        "",
    ]
    out_path = repo_root / "lab" / ".gen" / "kme-lab.conf"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def render_lab(
    *,
    repo_root: Path | None = None,
    ceos_image: str = DEFAULT_CEOS_IMAGE,
    mgmt_subnet: str = DEFAULT_MGMT_SUBNET,
) -> Path:
    root = repo_root or Path(__file__).resolve().parents[1]
    render_config_templates(repo_root=root, mgmt_subnet=mgmt_subnet, ceos_image=ceos_image)
    ips = mgmt_ips_for_subnet(mgmt_subnet)
    ips6 = mgmt_ipv6_ips_for_subnet()
    generate_radsec_pki(
        repo_root=root,
        radius_ip=ips6["radius"],
        syslog_ips=(ips["syslog"], ips6["syslog"]),
        ceos_hosts={"ceos1-both": "ceos1-both", "ceos2-pqc": "ceos2-pqc", "ceos3-qkd": "ceos3-qkd"},
        ceos_mgmt_ips={
            "ceos1-both": ips["ceos1-both"],
            "ceos2-pqc": ips["ceos2-pqc"],
            "ceos3-qkd": ips["ceos3-qkd"],
        },
    )
    generate_kme_pki(repo_root=root, kme_a_ip=ips["kme-a"], kme_b_ip=ips["kme-b"])
    render_kme_lab_conf(repo_root=root, mgmt_subnet=mgmt_subnet)
    topo_path = render_topology(
        repo_root=root,
        ceos_image=ceos_image,
        mgmt_subnet=mgmt_subnet,
        src=root / "lab" / "quantum-safe.clab.yml",
        dst=root / "lab" / ".gen.quantum-safe.clab.yml",
    )
    render_topology_annotations(repo_root=root)
    return topo_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render generated topology and mgmt-dependent configs.",
    )
    parser.add_argument(
        "--ceos-image",
        default=DEFAULT_CEOS_IMAGE,
        help=f"cEOS Docker tag (default: {DEFAULT_CEOS_IMAGE})",
    )
    parser.add_argument(
        "--mgmt-subnet",
        default=DEFAULT_MGMT_SUBNET,
        help=f"Management IPv4 subnet (default: {DEFAULT_MGMT_SUBNET})",
    )
    args = parser.parse_args(argv)

    try:
        topo_path = render_lab(ceos_image=args.ceos_image, mgmt_subnet=args.mgmt_subnet)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"rendered {topo_path.relative_to(Path(__file__).resolve().parents[1])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
