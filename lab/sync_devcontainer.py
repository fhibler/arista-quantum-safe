"""Sync Makefile CLAB_VERSION into .devcontainer/devcontainer.json."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MAKEFILE_CLAB_VERSION = re.compile(r"^CLAB_VERSION\s+\?=\s+(\S+)", re.M)
DEVCONTAINER_CLAB_VERSION = re.compile(r'("CLAB_VERSION":\s*")[^"]+(")')


def read_clab_version_from_makefile(makefile: Path) -> str:
    text = makefile.read_text(encoding="utf-8")
    match = MAKEFILE_CLAB_VERSION.search(text)
    if not match:
        raise ValueError(f"{makefile} must define CLAB_VERSION ?= <version>")
    return match.group(1)


def read_clab_version_from_devcontainer(devcontainer_json: Path) -> str:
    text = devcontainer_json.read_text(encoding="utf-8")
    match = DEVCONTAINER_CLAB_VERSION.search(text)
    if not match:
        raise ValueError(f'{devcontainer_json} must contain "CLAB_VERSION": "<version>"')
    start = text.find('"CLAB_VERSION"')
    snippet = text[start : start + 80]
    value_match = re.search(r':\s*"([^"]+)"', snippet)
    if not value_match:
        raise ValueError(f"{devcontainer_json} has malformed CLAB_VERSION entry")
    return value_match.group(1)


def sync_devcontainer(
    *,
    makefile: Path,
    devcontainer_json: Path,
    clab_version: str | None = None,
    check: bool = False,
) -> bool:
    """Return True when devcontainer.json already matched or was updated."""
    version = clab_version or read_clab_version_from_makefile(makefile)
    text = devcontainer_json.read_text(encoding="utf-8")
    updated, count = DEVCONTAINER_CLAB_VERSION.subn(
        lambda match: f"{match.group(1)}{version}{match.group(2)}",
        text,
        count=1,
    )
    if count != 1:
        raise ValueError(f'{devcontainer_json} must contain exactly one "CLAB_VERSION" entry')

    current = read_clab_version_from_devcontainer(devcontainer_json)
    if current == version:
        return True

    if check:
        print(
            f"{devcontainer_json}: CLAB_VERSION is {current!r}, expected {version!r} from {makefile}",
            file=sys.stderr,
        )
        return False

    devcontainer_json.write_text(updated, encoding="utf-8")
    print(f"Updated {devcontainer_json} CLAB_VERSION -> {version}")
    return True


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--makefile",
        type=Path,
        default=repo_root / "Makefile",
        help="Makefile containing CLAB_VERSION",
    )
    parser.add_argument(
        "--devcontainer-json",
        type=Path,
        default=repo_root / ".devcontainer" / "devcontainer.json",
        help="devcontainer.json to update",
    )
    parser.add_argument(
        "--clab-version",
        help="Containerlab version to write (default: CLAB_VERSION from Makefile)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero when devcontainer.json is out of sync (no writes)",
    )
    args = parser.parse_args(argv)

    try:
        ok = sync_devcontainer(
            makefile=args.makefile,
            devcontainer_json=args.devcontainer_json,
            clab_version=args.clab_version,
            check=args.check,
        )
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
