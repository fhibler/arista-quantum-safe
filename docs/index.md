# Quantum Safe Lab

Post-quantum cryptography (PQC) demonstration lab for **Arista EOS** using Containerlab.

## What this lab demonstrates

- **PQC-hybrid TLS 1.3** verified on eAPI, gNMI/gNOI, gNSI, gNPSI TLS/reflection, RESTCONF, RadSec, and remote syslog on EOS **4.37.0F**
- **PQC-hybrid SSH** KEX (`mlkem768x25519-sha256`) on VRF MGMT - also used by NETCONF
- **802.1X EAP-TLS + dynamic MACsec** on an inter-switch link, with EAP-TLS negotiated over PQC-hybrid groups via FreeRADIUS
- Automated **live verification** (`make test-lab`) with OpenSSL and EOS CLI probes

PQC applies to **key establishment only**. Server and client certificates remain classical (RSA/ECDSA) in this lab. See [PQC overview](pqc-overview.md) for terminology (non-PQC / PQC-safe / pure PQC) and Alpine OpenSSL policy.

## Lab policy

Most TLS ssl profiles list **only** the hybrid group `X25519MLKEM768` - no classical ECDH fallback. FreeRADIUS matches that strict policy; syslog-ng permits hybrid with classical fallback.

**Syslog and gNPSI TLS/reflection are PQC-safe** on the wire in 4.37.0F. Current results are in the [test summary](tests/index.md#result-summary); version history is in the [Changelog](changelog.md).

!!! warning "Remaining service limits"
    **gRIBI** and **eos-sdk-rpc** still negotiate classical KEX. **RESTCONF** negotiates hybrid when requested but also accepts classical TLS 1.3 and TLS 1.2 despite its strict profile. Syslog retains configured classical fallback. gNPSI Subscribe sample delivery remains **unverified**. See [Services](services/index.md) and the [test result summary](tests/index.md#result-summary).

## Quick links

- [PQC overview](pqc-overview.md) - algorithms, hybrid vs pure PQC, OpenSSL 3.5 minimum
- [Setup](setup.md) - prerequisites, deploy, Makefile reference
- [Services](services/index.md) - per-interface configuration and caveats
- [Certificates and TLS 1.3](misc/certificates-and-tls13.md) - PKI requirements and OpenSSL command examples
- [Tests](tests/index.md) - what `make test-lab` validates and how to reproduce checks manually

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

Startup templates live under `configs/ceos/*.cfg.in` and render to `lab/.gen/` via `make containerlab-gentopo`.
