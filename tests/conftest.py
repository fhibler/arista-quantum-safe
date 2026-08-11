"""Shared pytest fixtures for dual-stack lab tests."""

from __future__ import annotations

import pytest

from lab.topology_contract import IP_FAMILIES


@pytest.fixture(params=IP_FAMILIES)
def ip_family(request: pytest.FixtureRequest) -> str:
    """Parametrize tests over IPv4 and IPv6 address families."""
    return request.param
