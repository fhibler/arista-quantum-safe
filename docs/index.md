# Quantum Safe Lab

Post-quantum cryptography (PQC) demonstration lab for **Arista EOS** using Containerlab.

## What this lab demonstrates

- **PQC-hybrid-only TLS 1.3** on management interfaces: eAPI, gNMI/gNOI (gRPC), RESTCONF, RadSec, and remote syslog (where supported)
- **PQC-hybrid SSH** KEX (`mlkem768x25519-sha256`) on VRF MGMT — also used by NETCONF
- **802.1X EAP-TLS + dynamic MACsec** on an inter-switch link, with EAP-TLS negotiated over PQC-hybrid groups via FreeRADIUS
- Automated **live verification** (`make test-lab`) with OpenSSL and EOS CLI probes

PQC applies to **key establishment only**. Server and client certificates remain classical (RSA/ECDSA) in this lab. See [PQC overview](pqc-overview.md) for terminology (non-PQC / PQC-safe / pure PQC) and OpenSSL build requirements.

## Lab policy

Most TLS ssl profiles list **only** the hybrid group `X25519MLKEM768` — no classical ECDH fallback. Peers (FreeRADIUS, syslog-ng) match that policy where PQC-hybrid is enforced end-to-end.

!!! note "Known EOS gaps"
    **Syslog-over-TLS** and **eos-sdk-rpc** advertise PQC-hybrid in configuration but may negotiate classical key exchange on the wire. See [Services](services/index.md) for per-service caveats.

## Quick links

- [PQC overview](pqc-overview.md) — algorithms, hybrid vs pure PQC, OpenSSL container builds
- [Setup](setup.md) — prerequisites, deploy, Makefile reference
- [Services](services/index.md) — per-interface configuration and caveats
- [Certificates and TLS 1.3](misc/certificates-and-tls13.md) — PKI requirements and OpenSSL command examples
- [Tests](tests/index.md) — what `make test-lab` validates and how to reproduce checks manually

## Topology

Three EOS switches on a management network (`172.20.127.0/24` default) plus FreeRADIUS and syslog-ng collectors. Data-plane hosts attach via routed segments.

| Node | Mgmt IPv4 (default) | Notes |
|------|---------------------|-------|
| ceos1-both | 172.20.127.11 | Authenticator; dynamic MACsec on Ethernet1 |
| ceos2-pqc | 172.20.127.12 | Supplicant; dynamic MACsec on Ethernet1 |
| ceos3-qkd | 172.20.127.13 | Third switch (mgmt PQC checks) |
| radius | 172.20.127.50 | RadSec listener :2083 |
| syslog | 172.20.127.53 | TLS syslog :6514 |

Dual-stack IPv6 uses `2001:db8:127::/64` (documentation prefix).

Startup templates live under `configs/ceos/*.cfg.in` and render to `lab/.gen/` via `make gen-topo`.
