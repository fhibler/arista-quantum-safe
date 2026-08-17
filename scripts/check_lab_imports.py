"""Verify live lab Python imports and requirements-lab.txt stay in sync."""

from __future__ import annotations

import argparse
import ast
import importlib
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LAB_DIR = REPO_ROOT / "lab"
REQUIREMENTS_LAB_PATH = REPO_ROOT / "requirements-lab.txt"

# Entry points invoked by `make test-lab` / `test-lab-runner`.
TEST_LAB_MODULES = (
    "lab.topology_contract",
    "lab.test_lab",
    "lab.test_pqc_connections",
    "lab.test_kme",
    "lab.test_syslog",
    "lab.test_macsec",
    "lab.test_qkd",
    "lab.syslog_checks",
    "lab.probe_client",
    "lab.kme_http",
    "lab.ceos_json",
    "lab.report",
    "lab.verbose",
)

# Import name -> PyPI distribution name (when they differ).
IMPORT_TO_REQUIREMENT: dict[str, str] = {
    "yaml": "PyYAML",
}


def _module_path(module: str) -> Path:
    relative = module.removeprefix("lab.").replace(".", "/") + ".py"
    return LAB_DIR / relative


def third_party_imports(modules: tuple[str, ...] = TEST_LAB_MODULES) -> set[str]:
    """Return top-level third-party import names used by *modules*."""
    stdlib = set(sys.stdlib_module_names)
    found: set[str] = set()
    for module in modules:
        path = _module_path(module)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top not in stdlib and top != "lab":
                        found.add(top)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                if node.module:
                    top = node.module.split(".")[0]
                    if top not in stdlib and top != "lab":
                        found.add(top)
    return found


def required_packages(modules: tuple[str, ...] = TEST_LAB_MODULES) -> set[str]:
    return {IMPORT_TO_REQUIREMENT.get(name, name) for name in third_party_imports(modules)}


def parse_requirements_lab(path: Path = REQUIREMENTS_LAB_PATH) -> set[str]:
    packages: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = re.split(r"[<>=!~\[]", line, maxsplit=1)[0].strip()
        if name:
            packages.add(name)
    return packages


def requirements_are_synced(path: Path = REQUIREMENTS_LAB_PATH) -> bool:
    return parse_requirements_lab(path) == required_packages()


def import_lab_modules(modules: tuple[str, ...] = TEST_LAB_MODULES) -> None:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    for module in modules:
        importlib.import_module(module)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-imports",
        action="store_true",
        help="Import all live-lab modules (exit non-zero on ImportError)",
    )
    parser.add_argument(
        "--check-requirements",
        action="store_true",
        help="Exit non-zero when requirements-lab.txt does not match the import graph",
    )
    args = parser.parse_args(argv)

    if not args.check_imports and not args.check_requirements:
        args.check_imports = True
        args.check_requirements = True

    if args.check_requirements:
        expected = required_packages()
        actual = parse_requirements_lab()
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            parts: list[str] = []
            if missing:
                parts.append(f"missing from requirements-lab.txt: {', '.join(missing)}")
            if extra:
                parts.append(f"unexpected in requirements-lab.txt: {', '.join(extra)}")
            print("; ".join(parts), file=sys.stderr)
            return 1

    if args.check_imports:
        try:
            import_lab_modules()
        except ImportError as exc:
            print(f"lab import check failed: {exc}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
