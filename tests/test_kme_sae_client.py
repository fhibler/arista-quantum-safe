"""Unit tests for the ETSI QKD 014 SAE client."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lab.kme_sae_client import (
    KmeRadiusConfig,
    KmeSaeClient,
    KmeSaeError,
    _parse_key_container,
    fetch_enc_key_id,
    load_radius_config,
    roundtrip_keys,
)


def test_load_radius_config(tmp_path: Path) -> None:
    config_path = tmp_path / "radius-kme.conf"
    config_path.write_text(
        "\n".join(
            [
                "KME_A_HOST=10.0.0.51",
                "KME_A_PORT=8010",
                "KME_B_HOST=10.0.0.52",
                "KME_B_PORT=8020",
                "MASTER_SAE_ID=master-id",
                "SLAVE_SAE_ID=slave-id",
                "KEY_SIZE=32",
                "MASTER_CERT=/etc/kme/sae.crt.pem",
                "MASTER_KEY=/etc/kme/sae.key.pem",
                "SLAVE_CERT=/etc/kme/sae-b.crt.pem",
                "SLAVE_KEY=/etc/kme/sae-b.key.pem",
                "CA_CERT=/etc/kme/ca.crt.pem",
            ]
        ),
        encoding="utf-8",
    )
    cfg = load_radius_config(config_path)
    assert cfg.kme_a_host == "10.0.0.51"
    assert cfg.key_size == 32
    assert cfg.slave_sae_id == "slave-id"


def test_parse_key_container_validates_size() -> None:
    key_bytes = b"\x01" * 32
    payload = {
        "keys": [
            {
                "key_ID": "550e8400-e29b-41d4-a716-446655440000",
                "key": base64.b64encode(key_bytes).decode("ascii"),
            }
        ]
    }
    keys = _parse_key_container(payload, expected_size=32)
    assert keys[0].key_id == "550e8400-e29b-41d4-a716-446655440000"
    assert keys[0].key_bytes == key_bytes

    with pytest.raises(KmeSaeError, match="size 16 != expected 32"):
        _parse_key_container(
            {
                "keys": [
                    {
                        "key_ID": "550e8400-e29b-41d4-a716-446655440000",
                        "key": base64.b64encode(b"\x01" * 16).decode("ascii"),
                    }
                ]
            },
            expected_size=32,
        )


def _mock_urlopen(responses: dict[str, dict]) -> MagicMock:
    def _open(request: object, *args: object, **kwargs: object) -> MagicMock:
        url = getattr(request, "full_url", getattr(request, "get_full_url", lambda: "")())
        if url not in responses:
            raise AssertionError(f"unexpected URL: {url}")
        body = json.dumps(responses[url]).encode("utf-8")
        handle = MagicMock()
        handle.read.return_value = body
        handle.__enter__.return_value = handle
        handle.__exit__.return_value = False
        return handle

    return MagicMock(side_effect=_open)


def _mock_ssl_context() -> MagicMock:
    context = MagicMock()
    context.load_cert_chain.return_value = None
    context.check_hostname = False
    return context


def test_enc_keys_posts_aes256_request(tmp_path: Path) -> None:
    cert = tmp_path / "client.pem"
    key = tmp_path / "client.key"
    ca = tmp_path / "ca.pem"
    cert.write_text("cert", encoding="utf-8")
    key.write_text("key", encoding="utf-8")
    ca.write_text("ca", encoding="utf-8")

    key_bytes = b"\xab" * 32
    url = "https://10.0.0.51:8010/api/v1/keys/slave-id/enc_keys"
    mock_open = _mock_urlopen(
        {
            url: {
                "keys": [
                    {
                        "key_ID": "key-1",
                        "key": base64.b64encode(key_bytes).decode("ascii"),
                    }
                ]
            }
        }
    )

    with patch("lab.kme_sae_client.ssl.create_default_context", return_value=_mock_ssl_context()):
        with patch("lab.kme_sae_client.urllib.request.urlopen", mock_open):
            client = KmeSaeClient(
                host="10.0.0.51",
                port=8010,
                cert_path=cert,
                key_path=key,
                ca_path=ca,
            )
            keys = client.enc_keys("slave-id", number=1, size_bytes=32)

    assert keys[0].key_bytes == key_bytes
    request = mock_open.call_args.args[0]
    assert request.get_full_url() == url
    assert json.loads(request.data.decode("utf-8")) == {"number": 1, "size": 256}


def test_roundtrip_keys_matches_enc_and_dec(tmp_path: Path) -> None:
    key_bytes = b"\xcd" * 32
    key_id = "bc490419-7d60-487f-adc1-4ddcc177c139"
    enc_url = "https://10.0.0.51:8010/api/v1/keys/slave-id/enc_keys"
    dec_url = "https://10.0.0.52:8020/api/v1/keys/master-id/dec_keys"

    mock_open = _mock_urlopen(
        {
            enc_url: {
                "keys": [{"key_ID": key_id, "key": base64.b64encode(key_bytes).decode("ascii")}]
            },
            dec_url: {
                "keys": [{"key_ID": key_id, "key": base64.b64encode(key_bytes).decode("ascii")}]
            },
        }
    )

    cfg = KmeRadiusConfig(
        kme_a_host="10.0.0.51",
        kme_a_port=8010,
        kme_b_host="10.0.0.52",
        kme_b_port=8020,
        master_sae_id="master-id",
        slave_sae_id="slave-id",
        key_size=32,
        master_cert=tmp_path / "master.pem",
        master_key=tmp_path / "master.key",
        slave_cert=tmp_path / "slave.pem",
        slave_key=tmp_path / "slave.key",
        ca_cert=tmp_path / "ca.pem",
    )
    for path in (
        cfg.master_cert,
        cfg.master_key,
        cfg.slave_cert,
        cfg.slave_key,
        cfg.ca_cert,
    ):
        path.write_text("x", encoding="utf-8")

    with patch("lab.kme_sae_client.ssl.create_default_context", return_value=_mock_ssl_context()):
        with patch("lab.kme_sae_client.urllib.request.urlopen", mock_open):
            got_id, got_bytes = roundtrip_keys(cfg)

    assert got_id == key_id
    assert got_bytes == key_bytes


def test_fetch_enc_key_id_logs_without_printing_key_material(tmp_path: Path) -> None:
    log_path = tmp_path / "radius.log"
    cfg = KmeRadiusConfig(
        kme_a_host="10.0.0.51",
        kme_a_port=8010,
        kme_b_host="10.0.0.52",
        kme_b_port=8020,
        master_sae_id="master-id",
        slave_sae_id="slave-id",
        key_size=32,
        master_cert=tmp_path / "master.pem",
        master_key=tmp_path / "master.key",
        slave_cert=tmp_path / "slave.pem",
        slave_key=tmp_path / "slave.key",
        ca_cert=tmp_path / "ca.pem",
    )
    for path in (
        cfg.master_cert,
        cfg.master_key,
        cfg.slave_cert,
        cfg.slave_key,
        cfg.ca_cert,
    ):
        path.write_text("x", encoding="utf-8")

    key_bytes = b"\xef" * 32
    enc_url = "https://10.0.0.51:8010/api/v1/keys/slave-id/enc_keys"
    mock_open = _mock_urlopen(
        {
            enc_url: {
                "keys": [
                    {
                        "key_ID": "logged-key-id",
                        "key": base64.b64encode(key_bytes).decode("ascii"),
                    }
                ]
            }
        }
    )

    with patch("lab.kme_sae_client.ssl.create_default_context", return_value=_mock_ssl_context()):
        with patch("lab.kme_sae_client.urllib.request.urlopen", mock_open):
            with patch("lab.kme_sae_client.KME_LOG_PATH", log_path):
                key_id = fetch_enc_key_id(cfg)

    assert key_id == "logged-key-id"
    log_text = log_path.read_text(encoding="utf-8")
    assert "logged-key-id" in log_text
    assert "key_size=32" in log_text
    assert base64.b64encode(key_bytes).decode("ascii") not in log_text
