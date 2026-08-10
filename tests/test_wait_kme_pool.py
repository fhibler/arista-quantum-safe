"""Unit tests for KME pool wait helper."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from lab.wait_kme_pool import (
    KmePoolWaitError,
    fetch_slave_status,
    probe_enc_keys,
    wait_for_kme_pool,
)


def test_fetch_slave_status_parses_json() -> None:
    payload = {"stored_key_count": 3, "key_size": 256}
    with patch(
        "lab.wait_kme_pool._docker_curl",
        return_value=type("R", (), {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""})(),
    ):
        status = fetch_slave_status(
            radius_container="radius",
            kme_a_ip="10.0.0.51",
            slave_sae_id="slave-id",
        )
    assert status["stored_key_count"] == 3


def test_probe_enc_keys_accepts_uuid() -> None:
    key_id = "bc490419-7d60-487f-adc1-4ddcc177c139"
    with patch(
        "lab.wait_kme_pool.subprocess.run",
        return_value=type("R", (), {"returncode": 0, "stdout": key_id + "\n", "stderr": ""})(),
    ):
        got_id, err = probe_enc_keys("radius")
    assert got_id == key_id
    assert err is None


def test_probe_enc_keys_rejects_failure() -> None:
    with patch(
        "lab.wait_kme_pool.subprocess.run",
        return_value=type("R", (), {"returncode": 1, "stdout": "", "stderr": "boom"})(),
    ):
        got_id, err = probe_enc_keys("radius")
    assert got_id is None
    assert err == "boom"


def test_wait_for_kme_pool_honors_min_wait_and_probe() -> None:
    key_id = "550e8400-e29b-41d4-a716-446655440000"
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    with patch("lab.wait_kme_pool.wait_for_containers"), patch(
        "lab.wait_kme_pool.time.sleep", side_effect=fake_sleep
    ):
        with patch("lab.wait_kme_pool.time.monotonic", side_effect=[0.0, 0.0, 100.0]):
            with patch("lab.wait_kme_pool.probe_enc_keys", return_value=(key_id, None)):
                got = wait_for_kme_pool(
                    clab_name="qkd-macsec-radius",
                    mgmt_subnet="172.20.127.0/24",
                    min_wait_sec=15,
                    timeout_sec=60,
                )
    assert got == key_id
    assert sleeps[0] == 15


def test_wait_for_kme_pool_times_out() -> None:
    with patch("lab.wait_kme_pool.wait_for_containers"), patch("lab.wait_kme_pool.time.sleep"):
        with patch("lab.wait_kme_pool.time.monotonic", side_effect=[0.0, 0.0, 200.0]):
            with patch(
                "lab.wait_kme_pool.probe_enc_keys",
                return_value=(None, "pool empty"),
            ):
                with patch(
                    "lab.wait_kme_pool.fetch_slave_status",
                    return_value={"stored_key_count": 0},
                ):
                    with pytest.raises(KmePoolWaitError, match="not ready after"):
                        wait_for_kme_pool(
                            clab_name="qkd-macsec-radius",
                            mgmt_subnet="172.20.127.0/24",
                            min_wait_sec=1,
                            timeout_sec=5,
                        )
