"""Unit tests for live KME check helpers."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from lab.kme_http import KME_CA_CERT_CONTAINER
from lab.test_kme import (
    KmeCheckError,
    KmeTargets,
    assert_contains,
    dec_keys_on_kme_b,
    enc_keys_on_kme_a,
    run_kme_checks,
    run_kme_curl,
)
from lab.topology_contract import MGMT_IPS


def _kme_status_json(field: str = '"source_KME_ID"') -> str:
    return json.dumps({"keys": {field.strip('"'): "value"}})


def _enc_keys_json(key_id: str = "abc-123", key: str = "c2VjcmV0") -> str:
    return json.dumps({"keys": [{"key_ID": key_id, "key": key}]})


def _dec_keys_json(key_id: str = "abc-123", key: str = "c2VjcmV0") -> str:
    return json.dumps({"keys": [{"key_ID": key_id, "key": key}]})


def test_assert_contains_raises_with_label() -> None:
    with pytest.raises(KmeCheckError, match="missing"):
        assert_contains("hello", "world", label="missing")


def _kme_targets() -> KmeTargets:
    return KmeTargets(
        clab_name="quantum-safe",
        kme_a_ip=MGMT_IPS["kme-a"],
        kme_b_ip=MGMT_IPS["kme-b"],
    )


def test_enc_keys_on_kme_a_parses_response() -> None:
    targets = _kme_targets()
    with patch(
        "lab.test_kme.subprocess.run",
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=_enc_keys_json(), stderr=""),
    ):
        key_id, key_b64 = enc_keys_on_kme_a(targets)
    assert key_id == "abc-123"
    assert key_b64 == "c2VjcmV0"


def test_dec_keys_on_kme_b_validates_round_trip() -> None:
    targets = _kme_targets()
    with patch(
        "lab.test_kme.subprocess.run",
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=_dec_keys_json(), stderr=""),
    ):
        dec_keys_on_kme_b(targets, key_id="abc-123", key_b64="c2VjcmV0")

    with patch(
        "lab.test_kme.subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=_dec_keys_json(key="mismatch"),
            stderr="",
        ),
    ):
        with pytest.raises(KmeCheckError, match="does not match"):
            dec_keys_on_kme_b(targets, key_id="abc-123", key_b64="c2VjcmV0")


def test_run_kme_curl_omits_default_ca_cert_when_unset() -> None:
    captured: list[list[str]] = []

    def fake_run(argv, **kwargs: object):
        captured.append(list(argv))
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout='{"ok": true}', stderr="")

    with patch("lab.test_kme.subprocess.run", side_effect=fake_run):
        run_kme_curl(
            "kme-a SAE status",
            "arista-quantum-safe-kme-a",
            url="https://172.20.127.51:8010/api/v1/keys/id/status",
            cert="/certs/sae.crt.pem",
            key="/certs/sae.key.pem",
        )

    argv = captured[0]
    assert all(part is not None for part in argv)
    assert KME_CA_CERT_CONTAINER in argv


def test_run_kme_checks_happy_path(capsys) -> None:
    call = 0

    def fake_run(argv, **kwargs: object):
        nonlocal call
        call += 1
        url = next((arg for arg in argv if isinstance(arg, str) and arg.startswith("https://")), "")
        if url.endswith("/enc_keys"):
            stdout = _enc_keys_json()
        elif url.endswith("/dec_keys"):
            stdout = _dec_keys_json()
        elif "/kme/status" in url:
            stdout = json.dumps({"KME_ID": "kme-id"})
        else:
            stdout = _kme_status_json('"source_KME_ID"' if "8010" in url and "status" in url else '"stored_key_count"')
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=stdout, stderr="")

    with patch("lab.test_kme.subprocess.run", side_effect=fake_run):
        run_kme_checks(clab_name="quantum-safe", mgmt_subnet="172.20.127.0/24")

    out = capsys.readouterr().out
    assert "=== kme-a ===" in out
    assert "=== kme-b ===" in out
    assert "=== ceos1-both ===" in out
    assert "=== ceos3-qkd ===" in out
    assert "[kme]" in out
    assert "[host]" in out
    assert "KME: ✓" in out
    assert call >= 9
