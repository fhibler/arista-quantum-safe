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
