"""ETSI GS QKD 014 SAE client for the lab KME pair."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import ssl
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_KEY_SIZE_BYTES = 32  # AES-256; KEY_SIZE in radius-kme.conf is also bytes

DEFAULT_CONFIG_PATH = Path("/etc/kme/radius-kme.conf")

KME_LOG_PATH = Path("/var/log/radius/radius.log")


class KmeSaeError(RuntimeError):
    """Raised when a KME request fails."""


@dataclass(frozen=True)
class KmeKey:
    key_id: str
    key_bytes: bytes


@dataclass(frozen=True)
class KmeRadiusConfig:
    kme_a_host: str
    kme_a_port: int
    kme_b_host: str
    kme_b_port: int
    master_sae_id: str
    slave_sae_id: str
    key_size: int
    master_cert: Path
    master_key: Path
    slave_cert: Path
    slave_key: Path
    ca_cert: Path

    @classmethod
    def from_mapping(cls, values: dict[str, str]) -> KmeRadiusConfig:
        required = (
            "KME_A_HOST",
            "KME_A_PORT",
            "KME_B_HOST",
            "KME_B_PORT",
            "MASTER_SAE_ID",
            "SLAVE_SAE_ID",
            "KEY_SIZE",
            "MASTER_CERT",
            "MASTER_KEY",
            "SLAVE_CERT",
            "SLAVE_KEY",
            "CA_CERT",
        )
        missing = [name for name in required if not values.get(name)]
        if missing:
            raise KmeSaeError(f"missing config keys: {', '.join(missing)}")

        return cls(
            kme_a_host=values["KME_A_HOST"],
            kme_a_port=int(values["KME_A_PORT"]),
            kme_b_host=values["KME_B_HOST"],
            kme_b_port=int(values["KME_B_PORT"]),
            master_sae_id=values["MASTER_SAE_ID"],
            slave_sae_id=values["SLAVE_SAE_ID"],
            key_size=int(values["KEY_SIZE"]),
            master_cert=Path(values["MASTER_CERT"]),
            master_key=Path(values["MASTER_KEY"]),
            slave_cert=Path(values["SLAVE_CERT"]),
            slave_key=Path(values["SLAVE_KEY"]),
            ca_cert=Path(values["CA_CERT"]),
        )


def load_radius_config(path: Path | None = None) -> KmeRadiusConfig:
    """Load key=value settings written by make gen-topo."""
    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        raise KmeSaeError(f"KME config not found: {config_path}")

    values: dict[str, str] = {}
    for raw_line in config_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return KmeRadiusConfig.from_mapping(values)


class KmeSaeClient:
    """Minimal HTTPS+JSON+mTLS client for ETSI QKD 014 key delivery."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        cert_path: str | Path,
        key_path: str | Path,
        ca_path: str | Path,
    ) -> None:
        self._host = host
        self._port = port
        self._context = ssl.create_default_context(cafile=str(ca_path))
        self._context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
        self._context.check_hostname = False

    def _request(self, method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, context=self._context, timeout=30) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            raise KmeSaeError(f"KME HTTP {exc.code} for {url}: {detail or exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise KmeSaeError(f"KME request failed for {url}: {exc.reason}") from exc

        if not payload:
            return {}
        try:
            parsed = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise KmeSaeError(f"KME returned non-JSON from {url}") from exc
        if not isinstance(parsed, dict):
            raise KmeSaeError(f"KME returned unexpected JSON type from {url}")
        return parsed

    def get_status(self, slave_sae_id: str) -> dict[str, Any]:
        url = f"https://{self._host}:{self._port}/api/v1/keys/{slave_sae_id}/status"
        return self._request("GET", url)

    def enc_keys(
        self,
        slave_sae_id: str,
        *,
        number: int = 1,
        size_bytes: int = DEFAULT_KEY_SIZE_BYTES,
    ) -> list[KmeKey]:
        url = f"https://{self._host}:{self._port}/api/v1/keys/{slave_sae_id}/enc_keys"
        size_bits = size_bytes * 8
        payload = self._request("POST", url, {"number": number, "size": size_bits})
        return _parse_key_container(payload, expected_size=size_bytes)

    def dec_keys(self, master_sae_id: str, key_ids: list[str]) -> list[KmeKey]:
        url = f"https://{self._host}:{self._port}/api/v1/keys/{master_sae_id}/dec_keys"
        body = {"key_IDs": [{"key_ID": key_id} for key_id in key_ids]}
        payload = self._request("POST", url, body)
        return _parse_key_container(payload)


def _parse_key_container(payload: dict[str, Any], *, expected_size: int | None = None) -> list[KmeKey]:
    raw_keys = payload.get("keys")
    if not isinstance(raw_keys, list) or not raw_keys:
        raise KmeSaeError("KME response missing keys[]")

    keys: list[KmeKey] = []
    for item in raw_keys:
        if not isinstance(item, dict):
            raise KmeSaeError("KME keys[] entry is not an object")
        key_id = item.get("key_ID")
        key_b64 = item.get("key")
        if not isinstance(key_id, str) or not key_id:
            raise KmeSaeError("KME keys[] entry missing key_ID")
        if not isinstance(key_b64, str) or not key_b64:
            raise KmeSaeError(f"KME key {key_id} missing key material")

        try:
            key_bytes = base64.b64decode(key_b64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise KmeSaeError(f"KME key {key_id} is not valid base64") from exc

        if expected_size is not None and len(key_bytes) != expected_size:
            raise KmeSaeError(
                f"KME key {key_id} size {len(key_bytes)} != expected {expected_size}"
            )
        keys.append(KmeKey(key_id=key_id, key_bytes=key_bytes))
    return keys


def log_qkd_event(message: str, *, log_path: Path | None = None) -> None:
    """Append a non-secret audit line to radius.log (best-effort)."""
    target = log_path or KME_LOG_PATH
    try:
        with target.open("a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")
    except OSError:
        pass


def fetch_enc_key_id(config: KmeRadiusConfig | None = None) -> str:
    """Master SAE enc_keys on kme-a; logs key_ID and returns it (never key bytes)."""
    cfg = config or load_radius_config()
    client = KmeSaeClient(
        host=cfg.kme_a_host,
        port=cfg.kme_a_port,
        cert_path=cfg.master_cert,
        key_path=cfg.master_key,
        ca_path=cfg.ca_cert,
    )
    keys = client.enc_keys(cfg.slave_sae_id, number=1, size_bytes=cfg.key_size)
    key_id = keys[0].key_id
    log_qkd_event(
        f"QKD enc_keys key_ID={key_id} key_size={cfg.key_size} slave_sae={cfg.slave_sae_id}"
    )
    return key_id


def roundtrip_keys(config: KmeRadiusConfig | None = None) -> tuple[str, bytes]:
    """enc_keys on kme-a then dec_keys on kme-b; returns (key_id, key_bytes)."""
    cfg = config or load_radius_config()
    master = KmeSaeClient(
        host=cfg.kme_a_host,
        port=cfg.kme_a_port,
        cert_path=cfg.master_cert,
        key_path=cfg.master_key,
        ca_path=cfg.ca_cert,
    )
    slave = KmeSaeClient(
        host=cfg.kme_b_host,
        port=cfg.kme_b_port,
        cert_path=cfg.slave_cert,
        key_path=cfg.slave_key,
        ca_path=cfg.ca_cert,
    )

    enc = master.enc_keys(cfg.slave_sae_id, number=1, size_bytes=cfg.key_size)
    key_id = enc[0].key_id
    master_bytes = enc[0].key_bytes

    dec = slave.dec_keys(cfg.master_sae_id, [key_id])
    if len(dec) != 1:
        raise KmeSaeError(f"dec_keys returned {len(dec)} keys, expected 1")
    if dec[0].key_bytes != master_bytes:
        raise KmeSaeError("dec_keys material does not match enc_keys")
    return key_id, dec[0].key_bytes


def _cmd_fetch_enc_key(args: argparse.Namespace) -> int:
    try:
        config = load_radius_config(Path(args.config) if args.config else None)
        key_id = fetch_enc_key_id(config)
    except KmeSaeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(key_id)
    return 0


def _cmd_roundtrip(args: argparse.Namespace) -> int:
    try:
        config = load_radius_config(Path(args.config) if args.config else None)
        key_id, key_bytes = roundtrip_keys(config)
    except KmeSaeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps({"key_ID": key_id, "key_size": len(key_bytes)}, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ETSI QKD 014 SAE client for the lab.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch = subparsers.add_parser("fetch-enc-key", help="POST enc_keys on kme-a (stdout: key_ID)")
    fetch.add_argument("--config", help="Override /etc/kme/radius-kme.conf")
    fetch.set_defaults(func=_cmd_fetch_enc_key)

    trip = subparsers.add_parser("roundtrip", help="enc_keys on kme-a + dec_keys on kme-b")
    trip.add_argument("--config", help="Override /etc/kme/radius-kme.conf")
    trip.set_defaults(func=_cmd_roundtrip)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
