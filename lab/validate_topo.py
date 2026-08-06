"""CLI entry point for topology contract validation (Session 4 / R9)."""

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
    args = parser.parse_args(argv)

    topo_path = args.topology
    if not topo_path.is_file():
        print(f"topology file not found: {topo_path}", file=sys.stderr)
        return 1

    data = load_topology(topo_path)
    ceos_image = args.ceos_image
    if ceos_image is None:
        ceos_image = data.get("topology", {}).get("kinds", {}).get("arista_ceos", {}).get("image")

    errors = validate_topology(data, ceos_image=ceos_image)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
