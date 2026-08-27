# Post-quantum cryptography (PQC) overview

This page explains **terminology**, **algorithms used in the lab**, and **how lab containers get PQC-hybrid TLS** from Alpine 3.24 OpenSSL **3.5.7** (minimum PQC-safe OpenSSL: **3.5.0**) plus `OPENSSL_CONF`.

PQC in Arista EOS 4.35+ applies primarily to **key establishment** — how two peers agree on session keys. **Certificates and signatures** in this lab remain **classical** (RSA/ECDSA). Record-layer **AEAD ciphers** (for example `TLS_AES_256_GCM_SHA384`) are unchanged; security against harvest-now-decrypt-later attacks comes from **PQC-hybrid key exchange**, not from renaming those ciphers.

## Terminology

| Term | Meaning | Example in this lab |
|------|---------|---------------------|
| **Non-PQC (classical)** | Key exchange uses pre-quantum algorithms only | TLS groups `x25519`, `secp256r1`; SSH KEX without ML-KEM |
| **PQC-safe (live)** | A completed handshake negotiates a **hybrid** post-quantum key-establishment algorithm on the wire | TLS 1.3 group `X25519MLKEM768`; SSH `mlkem768x25519-sha256` |
| **Configurable for PQC** | EOS config or ssl profile **lists** a hybrid group, but the live client/server may still negotiate classical KEX | Syslog-over-TLS, gRIBI, gNPSI, and eos-sdk-rpc on EOS 4.36.2F — each marked with a **`Known EOS gap`** warning in [Services](services/index.md) |
| **Pure PQC** | Key exchange uses **only** a post-quantum algorithm, with **no** paired classical component | Standalone `MLKEM768` in OpenSSL group lists |

### Non-PQC vs PQC-safe

- **Non-PQC** connections can be broken in future by a cryptographically relevant quantum computer attacking the classical KEX step (for example ECDH on Curve25519).
- **PQC-safe** in this documentation means the lab has verified (or expects) negotiation of a **hybrid** construction that combines a classical algorithm with ML-KEM-768, so both must be broken to recover the session keys.
- **Configurable ≠ PQC-safe:** an ssl profile can advertise `X25519MLKEM768` while the actual TLS client offers only classical groups. Always verify on the wire (`make test-eapi`, `make test-syslog`, OpenSSL `s_client`, or packet capture) when that distinction matters.

### Hybrid PQC vs pure PQC

| | Hybrid PQC | Pure PQC |
|---|------------|----------|
| **Idea** | Run classical + post-quantum KEX together in one construction | Post-quantum KEX only |
| **TLS examples** | `X25519MLKEM768`, `SecP256r1MLKEM768` | `MLKEM768` (standalone group name in OpenSSL) |
| **SSH example** | `mlkem768x25519-sha256` | (not used in EOS / this lab) |
| **Transition role** | Preferred migration path while not all peers support pure PQC | Theoretical end-state for some designs |
| **This lab** | **Yes** — default policy | **No** |

!!! warning "Pure PQC is not used here — and is not ready for general deployment"
    **NIST has standardized ML-KEM** (FIPS 203), and OpenSSL 3.5+ can expose standalone groups such as `MLKEM768` in `openssl list -tls-groups`.

    However:

    - **IETF TLS interoperability** for production networks today centers on **hybrid** code points (draft/RFC track groups such as `X25519MLKEM768`), not pure-PQC-only TLS handshakes between heterogeneous vendors.
    - **Arista EOS ssl profiles** expose **hybrid** key-establishment tokens (for example `key-establishment-group X25519MLKEM768`), not standalone pure-PQC-only profiles.
    - **Pure-PQC-only** policy (hybrid groups disabled, classical fallback removed, only standalone ML-KEM offered) is **not ratified as a universal wire standard** and is **not** what this lab configures or tests.

    The lab intentionally uses **PQC-hybrid-only** (or hybrid-preferred) policy as the practical quantum-safe migration step.

## Algorithms and ciphers in this lab

### TLS 1.3 key-establishment groups (management plane)

| Group | Type | Used by lab policy? | Notes |
|-------|------|---------------------|-------|
| **`X25519MLKEM768`** | Hybrid (X25519 + ML-KEM-768) | **Yes** — primary | EOS ssl profiles `EAPI`, `RADSEC`, `GNMI`, `GRIBI`, `GNSI`, `GNPSI`, `RESTCONF`, `DOT1X`; strict peers (FreeRADIUS) |
| `ecdh_x25519` / `x25519` | Classical | Fallback only where explicitly allowed | SYSLOG profile and syslog-ng collector; EOS syslog **client** often negotiates this on the wire |
| `secp256r1`, `secp384r1`, … | Classical | Not in strict profiles | Appear in permissive probes / legacy clients |
| **`MLKEM768`** | Pure PQC | **No** on EOS | May appear in `openssl list -tls-groups` inside lab containers; not configured on switches |
| `SecP256r1MLKEM768` | Hybrid | **No** in this lab | OpenSSL 3.5 may list; lab templates use `X25519MLKEM768` |

IANA/OpenSSL code point for the hybrid group used in tests: **4588 (0x11ec)** for `X25519MLKEM768`.

### SSH key exchange (VRF MGMT)

| KEX algorithm | Type | Lab policy |
|---------------|------|------------|
| **`mlkem768x25519-sha256`** | Hybrid | **Yes** — `management ssh` on all EOS nodes |
| Classical SSH KEX (`curve25519-sha256`, …) | Non-PQC | Disabled for management SSH in lab templates |

NETCONF inherits SSH KEX from `management ssh`. SSH ciphers are restricted to **`aes256-gcm@openssh.com`** (AES-256-GCM only).

### TLS 1.3 record ciphers (AEAD)

These protect data **after** key establishment. The lab uses TLS **1.3 only** on PQC-managed ssl profiles:

```text
TLS_AES_256_GCM_SHA384
TLS_CHACHA20_POLY1305_SHA256
TLS_AES_128_GCM_SHA256
```

Configured on EOS as:

```text
cipher v1.3 TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256
```

Matching policy in `docker/radius/openssl-pqc.cnf` and `docker/syslog/openssl-pqc.cnf`.

These are **not** “PQC ciphers” in the sense of ML-KEM — they are standard TLS 1.3 AEAD suites. Quantum resistance for the session comes from the **hybrid KEX** step above.

### MACsec and QKD (out of band)

- **Dynamic MACsec (802.1X):** EAP-TLS inner tunnel uses ssl profile **`DOT1X`** with `X25519MLKEM768`. MACsec frame encryption uses MKA-derived keys ([MACsec service](services/macsec.md)).
- **QuaDRA / QKD:** Key material from ETSI GS QKD 014 KME APIs; separate from TLS group negotiation ([QKD service](services/qkd-etsi014.md)).

## Lab policy summary

| Layer | Policy |
|-------|--------|
| Strict ssl profiles (`EAPI`, `RADSEC`, `GNMI`, `GRIBI`, `GNSI`, `GNPSI`, `RESTCONF`, `DOT1X`) | **`X25519MLKEM768` only** — no classical ECDH fallback |
| FreeRADIUS RadSec | **`Groups = X25519MLKEM768`** via OpenSSL config |
| SSH management | **`mlkem768x25519-sha256`** preferred |
| SYSLOG profile | Hybrid listed **with classical fallback** (operational compromise for syslog client support) |

See [Services overview](services/index.md) for per-interface live PQC status.

## OpenSSL 3.5 (minimum for PQC-safe lab containers)

**OpenSSL 3.5.0** is the first OpenSSL release with **built-in** ML-KEM (FIPS 203) and the hybrid TLS groups this lab requires (`X25519MLKEM768`, `SecP256r1MLKEM768`). Earlier OpenSSL **3.2–3.4** lines do **not** advertise those groups without a third-party provider. This lab therefore treats **3.5.0** as the minimum OpenSSL version that is PQC-safe for TLS peers and probes.

EOS implements switch-side TLS natively. **Peer containers use Alpine 3.24 apk OpenSSL 3.5.7** (3.5 LTS; EOL 2030-04-08), which advertises `X25519MLKEM768`. Runtime policy is `OPENSSL_CONF` (PQC-hybrid groups only) — not a custom OpenSSL compile. See [Tool chain](misc/toolchain.md#probe-and-peer-client-summary) for per-client status, and [Setup](setup.md) for build targets (`make build-lab-images`, `make build-test-runner`, etc.).

FreeRADIUS **3.2.6** and syslog-ng **4.8.1** are still compiled from source (Alpine’s `freeradius` package is 3.0.x). They **link against apk OpenSSL**.

The **KME simulator** (`quantum-safe-kme:latest`) uses Python/Flask mTLS separately — see [QKD service](services/qkd-etsi014.md).

## Verify what your peer offers

Inside the radius container (same OpenSSL as RadSec probes):

```bash
docker exec arista-quantum-safe-radius openssl list -tls-groups
docker exec arista-quantum-safe-radius openssl version
```

On a switch:

```text
show management security ssl profile EAPI detail
show running-config section management ssh
```

Live hybrid negotiation:

```bash
make test-eapi VERBOSE=1
make test-ssh VERBOSE=1
make test-radsec VERBOSE=1
```

## Related

- [Services overview](services/index.md) — per-service configuration and caveats
- [Certificates and TLS 1.3](misc/certificates-and-tls13.md) — PKI requirements and OpenSSL command examples
- [Test suite overview](tests/index.md) — per-service make targets and result summary
- [Setup](setup.md) — build and deploy workflow
