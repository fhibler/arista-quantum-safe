"""Shared KME HTTP/curl helpers for lab scripts."""

from __future__ import annotations

KME_CURL_CONNECT_TIMEOUT_SEC = 5
KME_CURL_MAX_TIME_SEC = 15
DOCKER_EXEC_TIMEOUT_SEC = 20

KME_CURL_FLAGS = (
    "--connect-timeout",
    str(KME_CURL_CONNECT_TIMEOUT_SEC),
    "--max-time",
    str(KME_CURL_MAX_TIME_SEC),
)

KME_TLS_FLAGS = ("--tlsv1.3", "--tls-max", "1.3")

KME_CA_CERT_CONTAINER = "/certs/ca.crt.pem"

CEOS_MGMT_NETNS = "ns-MGMT"
CEOS_KME_CA_CERT = "/mnt/flash/kme-ca.crt.pem"
CEOS_KME_SAE_CERT = "/mnt/flash/kme-sae.crt.pem"
CEOS_KME_SAE_KEY = "/mnt/flash/kme-sae.key.pem"
CEOS_KME_SAE_B_CERT = "/mnt/flash/kme-sae-b.crt.pem"
CEOS_KME_SAE_B_KEY = "/mnt/flash/kme-sae-b.key.pem"


def kme_curl_tls_flags(*, strict: bool) -> tuple[str, ...]:
    """Return curl TLS flags; strict mode verifies the KME server chain (no -k)."""
    if strict:
        return ("-sf", *KME_TLS_FLAGS)
    return ("-sk",)


def kme_curl_argv(
    *,
    url: str,
    cert: str,
    key: str,
    ca_cert: str = KME_CA_CERT_CONTAINER,
    strict: bool = True,
    method: str = "GET",
    body: str | None = None,
) -> list[str]:
    """Build a curl argv list with optional strict server certificate verification."""
    argv = ["curl", *kme_curl_tls_flags(strict=strict), *KME_CURL_FLAGS]
    if strict:
        argv.extend(["--cacert", ca_cert])
    argv.extend(["--cert", cert, "--key", key])
    if method != "GET":
        argv.extend(["-X", method])
    if body is not None:
        argv.extend(["-H", "Content-Type: application/json", "-d", body])
    argv.append(url)
    return argv


def ceos_kme_curl_exec_argv(
    container: str,
    *,
    url: str,
    cert: str,
    key: str,
    ca_cert: str = CEOS_KME_CA_CERT,
    method: str = "GET",
    body: str | None = None,
) -> list[str]:
    """Build docker exec argv for strict mTLS curl from a cEOS MGMT VRF netns."""
    curl_argv = kme_curl_argv(
        url=url,
        cert=cert,
        key=key,
        ca_cert=ca_cert,
        strict=True,
        method=method,
        body=body,
    )
    return ["docker", "exec", container, "ip", "netns", "exec", CEOS_MGMT_NETNS, *curl_argv]
