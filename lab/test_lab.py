"""Live lab acceptance checks with optional verbose command echo and formatted output."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from typing import Sequence

from lab.report import (
    CheckStatus,
    ICON_OK,
    bold,
    report_check,
    report_summary,
)
from lab.test_hosts import HostRoutingError
from lab.topology_contract import (
    LAB_NAME,
    mgmt_ips_for_subnet,
    mgmt_ipv6_ips_for_subnet,
)

ALL_SECTIONS = (
    "inspect",
    "ssh",
    "eapi",
    "radsec",
    "syslog",
    "openconfig",
    "kme",
    "macsec-dot1x",
    "macsec-qkd",
    "hosts",
)


class LabTestError(RuntimeError):
    """Raised when a lab check fails."""


def section(title: str, *, verbose: bool) -> None:
    if not verbose:
        return
    bar = "=" * 78
    print(f"\n{bar}")
    print(bold(f"  {title}"))
    print(bar)


def run_step(
    title: str,
    argv: Sequence[str],
    *,
    input_text: str = "",
    verbose: bool = False,
    timeout_sec: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command; when verbose, echo argv and print captured output."""
    if verbose:
        print(f"\n--- {title} ---")
        print(f"$ {shlex.join(argv)}")
        if input_text:
            print("--- stdin ---")
            print(input_text.rstrip())
            print("--- end stdin ---")

    try:
        result = subprocess.run(
            list(argv),
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        raise LabTestError(f"{title} timed out after {timeout_sec}s") from exc

    if verbose:
        if result.stdout:
            print("--- stdout ---")
            print(result.stdout.rstrip())
        if result.stderr:
            print("--- stderr ---")
            print(result.stderr.rstrip())
        print(f"--- exit {result.returncode} ---")

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        message = f"{title} failed (exit {result.returncode}){': ' + detail if detail else ''}"
        if not verbose:
            report_check("[live]", message, CheckStatus.FAIL)
        raise LabTestError(message)
    return result


def format_json(raw: str) -> str:
    try:
        return json.dumps(json.loads(raw), indent=2, sort_keys=True)
    except json.JSONDecodeError:
        return raw.rstrip()


def run_inspect(clab_topo_gen: str, *, verbose: bool) -> None:
    section("INSPECT", verbose=verbose)
    run_step("containerlab inspect", ["containerlab", "inspect", "-t", clab_topo_gen], verbose=verbose)


def run_python_module(title: str, module: str, *args: str, verbose: bool = False) -> None:
    section(title.upper(), verbose=verbose)
    argv = [sys.executable, "-m", module, *args]
    if verbose:
        argv.append("--verbose")
        print(f"\n--- {title} ---")
        print(f"$ {shlex.join(argv)}")
    env = {**os.environ, "VERBOSE": "1"} if verbose else {k: v for k, v in os.environ.items() if k != "VERBOSE"}
    result = subprocess.run(argv, check=False, env=env)
    if verbose:
        print(f"--- exit {result.returncode} ---")
    if result.returncode != 0:
        raise LabTestError(f"{title} failed (exit {result.returncode})")


def run_sections(
    sections: Sequence[str],
    *,
    clab_name: str,
    clab_topo_gen: str,
    mgmt_subnet: str,
    verbose: bool,
) -> None:
    mgmt_ips_for_subnet(mgmt_subnet)
    mgmt_ipv6_ips_for_subnet()
    for index, name in enumerate(sections):
        if index > 0 and not verbose:
            print()
        if name == "inspect":
            run_inspect(clab_topo_gen, verbose=verbose)
        elif name == "radsec":
            run_python_module(
                "RadSec",
                "lab.test_radsec",
                "--clab-name",
                clab_name,
                "--mgmt-subnet",
                mgmt_subnet,
                verbose=verbose,
            )
        elif name == "kme":
            run_python_module(
                "KME",
                "lab.test_kme",
                "--clab-name",
                clab_name,
                "--mgmt-subnet",
                mgmt_subnet,
                verbose=verbose,
            )
        elif name == "eapi":
            run_python_module(
                "eAPI",
                "lab.test_eapi",
                "--clab-name",
                clab_name,
                "--mgmt-subnet",
                mgmt_subnet,
                verbose=verbose,
            )
        elif name == "ssh":
            run_python_module(
                "SSH",
                "lab.test_ssh",
                "--clab-name",
                clab_name,
                "--mgmt-subnet",
                mgmt_subnet,
                verbose=verbose,
            )
        elif name == "openconfig":
            run_python_module(
                "OpenConfig",
                "lab.test_openconfig",
                "--clab-name",
                clab_name,
                "--mgmt-subnet",
                mgmt_subnet,
                verbose=verbose,
            )
        elif name == "syslog":
            run_python_module(
                "Syslog",
                "lab.test_syslog",
                "--clab-name",
                clab_name,
                "--mgmt-subnet",
                mgmt_subnet,
                verbose=verbose,
            )
        elif name == "macsec-dot1x":
            run_python_module(
                "MACsec (802.1X)",
                "lab.test_macsec_dot1x",
                "--clab-name",
                clab_name,
                "--mgmt-subnet",
                mgmt_subnet,
                verbose=verbose,
            )
        elif name == "macsec-qkd":
            run_python_module(
                "MACsec (QuaDRA QKD)",
                "lab.test_macsec_qkd",
                "--clab-name",
                clab_name,
                verbose=verbose,
            )
        elif name == "hosts":
            run_python_module(
                "Hosts",
                "lab.test_hosts",
                "--clab-name",
                clab_name,
                verbose=verbose,
            )
        else:
            raise LabTestError(f"unknown section: {name}")

    if len(sections) > 1 and verbose:
        section("SUMMARY", verbose=True)
        print("All lab checks passed.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run live lab acceptance checks.")
    parser.add_argument("--clab-name", default=LAB_NAME)
    parser.add_argument(
        "--clab-topo-gen",
        default="lab/.gen.quantum-safe.clab.yml",
        help="Generated Containerlab topology file (inspect section only)",
    )
    parser.add_argument("--mgmt-subnet", default="172.20.127.0/24")
    parser.add_argument(
        "--section",
        action="append",
        dest="sections",
        choices=ALL_SECTIONS,
        help="Run one section (repeatable; default: all lab checks)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Echo commands and print full formatted output (also enabled by VERBOSE=1)",
    )
    args = parser.parse_args(argv)
    verbose = args.verbose or os.environ.get("VERBOSE") == "1"
    if args.sections:
        sections = args.sections
    elif verbose:
        sections = ALL_SECTIONS
    else:
        sections = ALL_SECTIONS[1:]

    try:
        run_sections(
            sections,
            clab_name=args.clab_name,
            clab_topo_gen=args.clab_topo_gen,
            mgmt_subnet=args.mgmt_subnet,
            verbose=verbose,
        )
    except (LabTestError, HostRoutingError, subprocess.CalledProcessError) as exc:
        report_summary("LAB", str(exc), CheckStatus.FAIL, file=sys.stderr)
        print(file=sys.stderr)
        return 1

    if len(sections) > 1 and not verbose:
        print()
        print(f"{ICON_OK} All lab checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
