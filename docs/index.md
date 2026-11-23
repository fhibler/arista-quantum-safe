# Quantum Safe Lab

Post-quantum cryptography (PQC) demonstration lab for **Arista EOS** using Containerlab.

**Tested EOS version: 4.37.0F.** The guides describe this lab version; release comparisons are in the [Changelog](changelog.md).

## What this lab demonstrates

- **PQC-hybrid TLS 1.3** verified on eAPI, gNMI/gNOI, gNSI, gNPSI TLS/reflection/Subscribe, RESTCONF, RadSec, and remote syslog on EOS **4.37.0F**
- **PQC-hybrid SSH** KEX (`mlkem768x25519-sha256`) on VRF MGMT - also used by NETCONF
- **802.1X EAP-TLS + dynamic MACsec** on an inter-switch link, with EAP-TLS negotiated over PQC-hybrid groups via FreeRADIUS
- Automated **live verification** (`make test-lab`) with OpenSSL and EOS CLI probes

PQC applies to **key establishment only**. Server and client certificates remain classical (RSA/ECDSA) in this lab. See [PQC overview](pqc-overview.md) for terminology (non-PQC / PQC-safe / pure PQC) and Alpine OpenSSL policy.

## Lab policy

Most TLS ssl profiles list **only** the hybrid group `X25519MLKEM768` - no classical ECDH fallback. FreeRADIUS matches that strict policy; syslog-ng permits hybrid with classical fallback.

**Syslog and gNPSI TLS/reflection/Subscribe are PQC-safe** on the wire in 4.37.0F. Current results are in the [test summary](tests/index.md#result-summary); version history is in the [Changelog](changelog.md).

!!! warning "Remaining service limits"
    **gRIBI** and **eos-sdk-rpc** still negotiate classical KEX. **RESTCONF** negotiates hybrid when requested but also accepts classical TLS 1.3 and TLS 1.2 despite its strict profile. Syslog retains configured classical fallback. See [Services](services/index.md) and the [test result summary](tests/index.md#result-summary).

## Quick links

- [PQC overview](pqc-overview.md) - algorithms, hybrid vs pure PQC, OpenSSL 3.5 minimum
- [Setup](setup.md) - prerequisites, deploy, Makefile reference
- [Services](services/index.md) - per-interface configuration and caveats
- [Certificates and TLS 1.3](misc/certificates-and-tls13.md) - PKI requirements and OpenSSL command examples
- [Tests](tests/index.md) - what `make test-lab` validates and how to reproduce checks manually

## Topology

The service containers (`radius`, `syslog`, `kme-a`, `kme-b`, and `test-runner`) connect to all three cEOS instances through the **shared Docker management network `quantum-safe-mgmt`**, backed by `mgmt-bridge`. The default subnets are `172.20.127.0/24` and `2001:db8:127::/64`; cEOS uses **Management0 in VRF `MGMT`**. Service traffic uses this network independently of the inter-switch data links.

[![Lab topology: grouped service containers share the management network with three cEOS switches. ceos3-qkd connects to ceos1-both through static MACsec, with optional QuaDRA rotation using simulated QKD keys; ceos1-both connects to ceos2-pqc through dynamic MACsec using hybrid EAP-TLS and MKA. Each switch has a routed host link without MACsec.](assets/images/lab-topology-light.svg#only-light)](assets/images/lab-topology-light.svg#only-light)
[![Lab topology: grouped service containers share the management network with three cEOS switches. ceos3-qkd connects to ceos1-both through static MACsec, with optional QuaDRA rotation using simulated QKD keys; ceos1-both connects to ceos2-pqc through dynamic MACsec using hybrid EAP-TLS and MKA. Each switch has a routed host link without MACsec.](assets/images/lab-topology-dark.svg#only-dark)](assets/images/lab-topology-dark.svg#only-dark)

*Select the diagram to view it at full size. Dashed lines show shared management connectivity; solid lines show data links.*

- **Management services:** [RadSec](services/radius-radsec.md) and [syslog](services/syslog.md) negotiate hybrid TLS 1.3; syslog retains configured classical fallback. The test client probes EOS management APIs and SSH; service-specific KEX and policy limits are listed in the [test results](tests/index.md#result-summary).
- **Inter-switch encryption:** [Dynamic MACsec](services/macsec.md) derives keys from hybrid EAP-TLS via FreeRADIUS. The separate [static MACsec link](services/qkd-etsi014.md) uses preconfigured keys at startup; rotation using simulated QKD keys requires the optional QuaDRA extension. Both QuaDRA-to-KME mTLS connections negotiated hybrid TLS 1.3 over IPv4; hybrid-only enforcement is **unverified**.
- **Host access:** Each Alpine host has a routed data link without MACsec. Hosts also attach to the shared management network on `eth0`; those management connections are omitted from the diagram for clarity.

| Node | Mgmt IPv4 (default) | Mgmt IPv6 (default) | Notes |
|------|---------------------|---------------------|-------|
| ceos1-both | 172.20.127.11 | 2001:db8:127::11 | Authenticator; dynamic MACsec on Ethernet1, static MACsec on Ethernet2 |
| ceos2-pqc | 172.20.127.12 | 2001:db8:127::12 | Supplicant; dynamic MACsec on Ethernet1 |
| ceos3-qkd | 172.20.127.13 | 2001:db8:127::13 | Static MACsec on Ethernet1 toward ceos1-both:Ethernet2; optional QuaDRA key rotation |
| radius | 172.20.127.50 | 2001:db8:127::50 | RadSec listener :2083 |
| kme-a | 172.20.127.51 | 2001:db8:127::51 | ETSI QKD 014 simulator; HTTPS mTLS :8010 |
| kme-b | 172.20.127.52 | 2001:db8:127::52 | ETSI QKD 014 simulator; HTTPS mTLS :8020 |
| syslog | 172.20.127.53 | 2001:db8:127::53 | TLS syslog :6514 |
| test-runner | 172.20.127.54 | 2001:db8:127::54 | OpenSSL 3.5 + curl probe client |

Dual-stack IPv6 uses `2001:db8:127::/64` (documentation prefix).

Startup templates live under `configs/ceos/*.cfg.in` and render to `lab/.gen/` via `make containerlab-gentopo`.
