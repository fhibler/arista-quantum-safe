"""Wait for KME key pool readiness after staged deploy of RADIUS + KME nodes."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time

from lab.kme_http import DOCKER_EXEC_TIMEOUT_SEC, KME_CURL_FLAGS
from lab.topology_contract import KME_B_SAE_ID, mgmt_ips_for_subnet

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# KEY_GEN_SEC_TO_GEN=30; deploy already staggers kme-b (+10s) and radius (+15s).
DEFAULT_MIN_WAIT_SEC = 15
DEFAULT_TIMEOUT_SEC = 90
POLL_INTERVAL_SEC = 5


class KmePoolWaitError(RuntimeError):
    """Raised when KME pool readiness cannot be confirmed."""


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


def wait_for_containers(*names: str, timeout_sec: int = 60) -> None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if all(container_running(name) for name in names):
            return
        time.sleep(2)
    missing = [name for name in names if not container_running(name)]
    raise KmePoolWaitError(f"containers not running: {', '.join(missing)}")


def _docker_curl(
    *,
    container: str,
    url: str,
    cert: str,
    key: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "docker",
            "exec",
            container,
            "curl",
            "-sfk",
            *KME_CURL_FLAGS,
            "--cert",
            cert,
            "--key",
            key,
            url,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=DOCKER_EXEC_TIMEOUT_SEC,
    )


def fetch_slave_status(*, radius_container: str, kme_a_ip: str, slave_sae_id: str) -> dict[str, object]:
    url = f"https://{kme_a_ip}:8010/api/v1/keys/{slave_sae_id}/status"
    result = _docker_curl(
        container=radius_container,
        url=url,
        cert="/etc/kme/sae.crt.pem",
        key="/etc/kme/sae.key.pem",
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise KmePoolWaitError(f"status request failed{': ' + detail if detail else ''}")
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise KmePoolWaitError("status response is not a JSON object")
    return payload


def probe_enc_keys(radius_container: str) -> tuple[str | None, str | None]:
    """Return (key_id, error_detail) — key_id set when enc_keys succeeds."""
    result = subprocess.run(
        [
            "docker",
            "exec",
            radius_container,
            "sh",
            "-c",
            "PYTHONPATH=/opt/qkd python3 -m lab.kme_sae_client fetch-enc-key",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=DOCKER_EXEC_TIMEOUT_SEC,
    )
    key_id = result.stdout.strip()
    if result.returncode == 0 and UUID_RE.match(key_id):
        return key_id, None
    detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
    return None, detail


def wait_for_kme_pool(
    *,
    clab_name: str,
    mgmt_subnet: str,
    min_wait_sec: int = DEFAULT_MIN_WAIT_SEC,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    verbose: bool = False,
) -> str:
    """Block until enc_keys succeeds; return the probe key_ID."""
    ips = mgmt_ips_for_subnet(mgmt_subnet)
    radius_container = f"clab-{clab_name}-radius"
    kme_a_container = f"clab-{clab_name}-kme-a"
    kme_b_container = f"clab-{clab_name}-kme-b"

    log("Waiting for KME/RADIUS containers...", force=True)
    wait_for_containers(radius_container, kme_a_container, kme_b_container)
    log(
        f"KME/RADIUS up; waiting {min_wait_sec}s for key generation "
        f"(then polling up to {timeout_sec}s)...",
        force=True,
    )
    time.sleep(min_wait_sec)

    deadline = time.monotonic() + timeout_sec
    last_count: int | None = None
    last_error: str | None = None
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        key_id, enc_error = probe_enc_keys(radius_container)
        if key_id:
            return key_id

        last_error = enc_error
        try:
            status = fetch_slave_status(
                radius_container=radius_container,
                kme_a_ip=ips["kme-a"],
                slave_sae_id=KME_B_SAE_ID,
            )
            last_count = int(status.get("stored_key_count", 0) or 0)
        except (KmePoolWaitError, json.JSONDecodeError, TypeError, ValueError):
            last_count = None

        log(
            f"  poll {attempt}: enc_keys not ready"
            + (f" (stored_key_count={last_count})" if last_count is not None else "")
            + (f" — {enc_error}" if verbose and enc_error else ""),
            force=True,
        )
        time.sleep(POLL_INTERVAL_SEC)

    raise KmePoolWaitError(
        f"KME pool not ready after {timeout_sec}s "
        f"(min wait {min_wait_sec}s; last stored_key_count={last_count}; "
        f"last enc_keys error={last_error!r})"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Wait for KME key pool after staged RADIUS/KME deploy.",
    )
    parser.add_argument("--clab-name", default="qkd-macsec-radius")
    parser.add_argument("--mgmt-subnet", default="172.20.127.0/24")
    parser.add_argument(
        "--min-wait",
        type=int,
        default=DEFAULT_MIN_WAIT_SEC,
        help=f"Seconds to wait after containers are up (default: {DEFAULT_MIN_WAIT_SEC})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SEC,
        help=f"Seconds to poll after min-wait (default: {DEFAULT_TIMEOUT_SEC})",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    try:
        key_id = wait_for_kme_pool(
            clab_name=args.clab_name,
            mgmt_subnet=args.mgmt_subnet,
            min_wait_sec=args.min_wait,
            timeout_sec=args.timeout,
            verbose=args.verbose,
        )
    except KmePoolWaitError as exc:
        print(f"KME pool wait failed: {exc}", file=sys.stderr)
        return 1

    print(f"KME pool ready (enc_keys key_ID={key_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
