"""CLI entry point for topology contract validation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lab.topology_contract import GEN_TOPOLOGY_PATH, load_topology, validate_topology


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a Containerlab topology against the lab contract.",
    )
    parser.add_argument(
        "topology",
        nargs="?",
        type=Path,
        default=GEN_TOPOLOGY_PATH,
        help=f"Topology YAML path (default: {GEN_TOPOLOGY_PATH})",
    )
    parser.add_argument(
        "--ceos-image",
        default=None,
        help="Expected arista_ceos image tag (default: value from topology)",
    )
    parser.add_argument(
        "--mgmt-subnet",
        default=None,
        help="Expected mgmt IPv4 subnet (default: value from topology)",
    )
    parser.add_argument(
        "--mgmt-ipv6-subnet",
        default=None,
        help="Expected mgmt IPv6 subnet (default: value from topology)",
    )
    args = parser.parse_args(argv)

    topo_path = args.topology
    if not topo_path.is_file():
        print(f"topology file not found: {topo_path}", file=sys.stderr)
        return 1

    data = load_topology(topo_path)
    ceos_image = args.ceos_image
    if ceos_image is None:
        ceos_image = data.get("topology", {}).get("kinds", {}).get("arista_ceos", {}).get("image")

    mgmt_subnet = args.mgmt_subnet
    if mgmt_subnet is None:
        mgmt_subnet = data.get("mgmt", {}).get("ipv4-subnet")

    mgmt_ipv6_subnet = args.mgmt_ipv6_subnet
    if mgmt_ipv6_subnet is None:
        mgmt_ipv6_subnet = data.get("mgmt", {}).get("ipv6-subnet")

    errors = validate_topology(
        data,
        ceos_image=ceos_image,
        mgmt_subnet=mgmt_subnet,
        mgmt_ipv6_subnet=mgmt_ipv6_subnet,
    )
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
