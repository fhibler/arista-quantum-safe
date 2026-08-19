# Services

PQC-hybrid configuration for each management-plane and data-plane security service in the lab. All services use **VRF MGMT** unless noted.

Templates: `configs/ceos/ceos*.cfg.in` -> rendered to `lab/.gen/` via `make gen-topo`.

## Summary

| Service | Port | ssl profile / KEX | Config PQC? | Live PQC? | Doc |
|---------|------|-------------------|-------------|-----------|-----|
| [SSH / NETCONF](ssh.md) | 22 | `mlkem768x25519-sha256` | Yes | **Yes** | [ssh.md](ssh.md) |
| [eAPI](eapi.md) | 443 | `EAPI` | Yes | **Yes** | [eapi.md](eapi.md) |
| [gNMI](openconfig.md#gnmi-gnoi-grpc) | 6030 | `GNMI` | Yes | **Yes** | [openconfig.md](openconfig.md) |
| [gNOI](openconfig.md#gnmi-gnoi-grpc) | 6030 | `GNMI` (shared) | Yes | **Yes** | [openconfig.md](openconfig.md) |
| [gRIBI](openconfig.md#gribi-grpc) | 9340 | `GRIBI` | Yes | **No** (wire) | [openconfig.md](openconfig.md) |
| [gNSI](openconfig.md#gnsi-grpc) | 6030 (`transport gnmi default`) | `GNSI` (+ wire `GNMI`) | Yes | **Yes** (Certz; `-u admin`) | [openconfig.md](openconfig.md) |
| [gNPSI](openconfig.md#gnpsi-grpc-sflow-proxy) | 6031 | `GNPSI` | Yes | **No** (wire); Subscribe live (WARN) | [openconfig.md](openconfig.md) |
| [RESTCONF](openconfig.md#restconf-https) | 6020 | `RESTCONF` | Yes | **Yes** | [openconfig.md](openconfig.md) |
| [eos-sdk-rpc](openconfig.md#eos-sdk-rpc-grpc-mtls) | 9543 | `GNMI` (reused) | Yes | **No** (WARN) | [openconfig.md](openconfig.md) |
| [RadSec](radius-radsec.md) | 2083 | `RADSEC` | Yes | **Yes** | [radius-radsec.md](radius-radsec.md) |
| [Syslog-over-TLS](syslog.md) | 6514 | `SYSLOG` | Yes | **No** (WARN) | [syslog.md](syslog.md) |
| [MACsec (802.1X)](macsec.md) | — | EAP-TLS via `DOT1X` | Yes | **Yes** (EAP-TLS) | [macsec.md](macsec.md) |
| [QKD / QuaDRA](qkd-etsi014.md) | 8010/8020 | ETSI 014 mTLS | Yes | **With extension** | [qkd-etsi014.md](qkd-etsi014.md) |

!!! note "Terminology"
    - **Non-PQC** — classical key exchange only (for example `x25519`, `secp256r1`).
    - **PQC-safe (live)** — hybrid group negotiated on the wire (for example `X25519MLKEM768`).
    - **Pure PQC** — post-quantum KEX without a classical component; **not used** in this lab ([PQC overview](../pqc-overview.md)).
    - **Config PQC** — hybrid group appears in EOS config / passes `[config]` checks.
    - Certificates stay classical (RSA/ECDSA); PQC applies to **key establishment** only.

Each service page follows the same chapter order: **Configuration** (ssl profile + service binding, plus peer/collector config where applicable) → **Caveats** (`| Topic | Status on EOS |` table and admonitions) → **Verification** (CLI/probe commands, then **`make test-*`**). Multi-service pages ([OpenConfig & gRPC](openconfig.md)) repeat that pattern per protocol section.

## Lab policy

Strict profiles (`EAPI`, `RADSEC`, `GNMI`, `RESTCONF`, `DOT1X`) list **only** `X25519MLKEM768` — no classical ECDH fallback. FreeRADIUS uses matching OpenSSL policy (`docker/radius/openssl-pqc.cnf`).

**Exceptions:** The SYSLOG profile and syslog-ng collector allow classical fallback so remote logging works while the EOS syslog TLS client may lack PQC-hybrid support on the wire. See [Syslog caveats](syslog.md#caveats).

**Known EOS wire gaps (4.36.2F):** [Syslog](syslog.md#caveats), [gRIBI](openconfig.md#gribi-grpc), [gNPSI](openconfig.md#gnpsi-grpc-sflow-proxy), and [eos-sdk-rpc](openconfig.md#eos-sdk-rpc-grpc-mtls) advertise PQC-hybrid in configuration but may negotiate classical key exchange on the wire. Each page marks the gap with a **`Known EOS gap`** warning in its Caveats section.

## Service guides

| Guide | Covers |
|-------|--------|
| [SSH](ssh.md) | OpenSSH KEX, VRF MGMT, NETCONF transport |
| [eAPI](eapi.md) | HTTPS JSON-RPC on port 443 |
| [OpenConfig & gRPC](openconfig.md) | gNMI, gNOI, gRIBI, gNSI, gNPSI, RESTCONF, eos-sdk-rpc |
| [Syslog](syslog.md) | Remote TLS logging to syslog-ng |
| [RADIUS / RadSec](radius-radsec.md) | RadSec AAA and EAP-TLS for 802.1X |
| [MACsec](macsec.md) | Dynamic MACsec on ceos1-both <-> ceos2-pqc |
| [QKD / ETSI 014 & QuaDRA](qkd-etsi014.md) | KME simulators + QuaDRA static SAK rotation (extension via Arista) |

## Related

- [Setup](../setup.md) — deploy prerequisites and Makefile targets
- [Certificates and TLS 1.3](../misc/certificates-and-tls13.md) — PKI requirements and OpenSSL examples
- [Test suite overview](../tests/index.md) — per-service make targets (eAPI, SSH, RadSec, syslog, OpenConfig, KME, MACsec, hosts)
- [OpenConfig tests](../tests/openconfig.md) — `make test-openconfig` (gNMI, gNOI, gRIBI, gNSI, gNPSI, RESTCONF, eos-sdk-rpc)
- [KME tests](../tests/kme.md) — `make test-kme` (ETSI QKD 014)
- [Host routing tests](../tests/hosts.md) — `make test-hosts`
