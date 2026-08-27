"""Shared exceptions for live lab checks."""

from __future__ import annotations


class PqcConnectionError(RuntimeError):
    """Raised when a live PQC connectivity check fails."""
