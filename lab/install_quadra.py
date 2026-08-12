"""Copy and install the QuaDRA EOS extension on ceos1-both and ceos3-qkd."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

from lab.topology_contract import (
    CEOS_QUADRA_NODES,
    LAB_NAME,
    container_name,
    quadra_arch_suffix,
    quadra_swix_glob_pattern,
    quadra_swix_path,
    resolve_quadra_swix,
)

DOCKER_EXEC_TIMEOUT_SEC = 120
INSTALLED_RE = re.compile(r"\bI\b")


class InstallQuadraError(RuntimeError):
    """Raised when QuaDRA extension installation fails."""


def log(message: str, *, verbose: bool = False, force: bool = False) -> None:
    if force or verbose:
        print(message, flush=True)


def container_running(name: str) -> bool:
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", name],
        capture_output=True,
        text=True,
        check=False,
        timeout=DOCKER_EXEC_TIMEOUT_SEC,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def run_cli(container: str, commands: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "exec", "-i", container, "Cli"],
        input=commands,
        text=True,
        capture_output=True,
        check=False,
        timeout=DOCKER_EXEC_TIMEOUT_SEC,
    )


def extension_installed(stdout: str, swix: str) -> bool:
    for line in stdout.splitlines():
        if swix not in line:
            continue
        if INSTALLED_RE.search(line):
            return True
    return False


def install_on_node(
    node: str,
    *,
    clab_name: str,
    swix_path: str,
    verbose: bool,
) -> None:
    container = container_name(node, lab_name=clab_name)
    swix = swix_path.rsplit("/", 1)[-1]

    if not container_running(container):
        raise InstallQuadraError(f"container not running: {container}")

    show = run_cli(container, "enable\nshow extensions\n")
    if show.returncode != 0:
        detail = show.stderr.strip() or show.stdout.strip()
        raise InstallQuadraError(f"{node}: show extensions failed: {detail}")

    if extension_installed(show.stdout, swix):
        log(f"{node}: {swix} already installed", force=True, verbose=verbose)
        enable_daemon(container, node, verbose=verbose)
        return

    log(f"{node}: copying {swix} to flash", verbose=verbose, force=True)
    cp = subprocess.run(
        ["docker", "cp", swix_path, f"{container}:/mnt/flash/{swix}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=DOCKER_EXEC_TIMEOUT_SEC,
    )
    if cp.returncode != 0:
        detail = cp.stderr.strip() or cp.stdout.strip()
        raise InstallQuadraError(f"{node}: docker cp failed: {detail}")

    install = run_cli(
        container,
        "\n".join(
            (
                "enable",
                f"copy flash:{swix} extension:",
                f"extension {swix}",
                "copy installed-extensions boot-extensions",
                "show extensions",
                "",
            )
        ),
    )
    if install.returncode != 0:
        detail = install.stderr.strip() or install.stdout.strip()
        raise InstallQuadraError(f"{node}: extension install failed: {detail}")
    if not extension_installed(install.stdout, swix):
        raise InstallQuadraError(
            f"{node}: {swix} not reported as installed:\n{install.stdout.strip()}"
        )

    log(f"{node}: installed {swix}", force=True, verbose=verbose)

    enable_daemon(container, node, verbose=verbose)


def enable_daemon(container: str, node: str, *, verbose: bool) -> None:
    """Start the QuaDRA agent when the extension is present."""
    show = run_cli(container, "enable\nshow daemon quadra\n")
    if show.returncode != 0:
        detail = show.stderr.strip() or show.stdout.strip()
        raise InstallQuadraError(f"{node}: show daemon quadra failed: {detail}")
    if "running with PID" in show.stdout:
        log(f"{node}: daemon quadra already running", force=True, verbose=verbose)
        return

    log(f"{node}: starting daemon quadra", verbose=verbose, force=True)
    start = run_cli(
        container,
        "\n".join(
            (
                "enable",
                "configure",
                "daemon quadra",
                "no shutdown",
                "end",
                "show daemon quadra",
                "",
            )
        ),
    )
    if start.returncode != 0:
        detail = start.stderr.strip() or start.stdout.strip()
        raise InstallQuadraError(f"{node}: daemon quadra start failed: {detail}")
    if "running with PID" not in start.stdout:
        raise InstallQuadraError(
            f"{node}: daemon quadra not running after no shutdown:\n{start.stdout.strip()}"
        )
    log(f"{node}: daemon quadra running", force=True, verbose=verbose)


def install_quadra(*, clab_name: str, verbose: bool = False) -> None:
    swix = resolve_quadra_swix()
    if swix is None:
        arch = quadra_arch_suffix()
        pattern = quadra_swix_glob_pattern()
        default_dir = quadra_swix_path().parent
        raise InstallQuadraError(
            f"QuaDRA swix not found for {arch}. "
            f"Place {pattern} under {default_dir}/ "
            f"or set QUADRA_SWIX=/path/to/file.swix"
        )

    log(f"Using QuaDRA swix: {swix}", force=True, verbose=verbose)
    for node in sorted(CEOS_QUADRA_NODES):
        install_on_node(node, clab_name=clab_name, swix_path=str(swix), verbose=verbose)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install the QuaDRA EOS extension on ceos1-both and ceos3-qkd.",
    )
    parser.add_argument("--clab-name", default=LAB_NAME)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    try:
        install_quadra(clab_name=args.clab_name, verbose=args.verbose)
    except InstallQuadraError as exc:
        print(f"QuaDRA install failed: {exc}", file=sys.stderr)
        return 1

    print("QuaDRA extension installed on ceos1-both and ceos3-qkd.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
