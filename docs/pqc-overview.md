# Post-quantum cryptography (PQC) overview

This page explains **terminology**, **algorithms used in the lab**, and **why several Docker images are built from source** against OpenSSL 3.5+.

PQC in Arista EOS 4.35+ applies primarily to **key establishment** — how two peers agree on session keys. **Certificates and signatures** in this lab remain **classical** (RSA/ECDSA). Record-layer **AEAD ciphers** (for example `TLS_AES_256_GCM_SHA384`) are unchanged; security against harvest-now-decrypt-later attacks comes from **PQC-hybrid key exchange**, not from renaming those ciphers.

## Terminology

| Term | Meaning | Example in this lab |
|------|---------|---------------------|
| **Non-PQC (classical)** | Key exchange uses pre-quantum algorithms only | TLS groups `x25519`, `secp256r1`; SSH KEX without ML-KEM |
| **PQC-safe (live)** | A completed handshake negotiates a **hybrid** post-quantum key-establishment algorithm on the wire | TLS 1.3 group `X25519MLKEM768`; SSH `mlkem768x25519-sha256` |
| **Configurable for PQC** | EOS config or ssl profile **lists** a hybrid group, but the live client/server may still negotiate classical KEX | Syslog-over-TLS on EOS (see [Syslog service](services/syslog.md)) |
| **Pure PQC** | Key exchange uses **only** a post-quantum algorithm, with **no** paired classical component | Standalone `MLKEM768` in OpenSSL group lists |

### Non-PQC vs PQC-safe

- **Non-PQC** connections can be broken in future by a cryptographically relevant quantum computer attacking the classical KEX step (for example ECDH on Curve25519).
- **PQC-safe** in this documentation means the lab has verified (or expects) negotiation of a **hybrid** construction that combines a classical algorithm with ML-KEM-768, so both must be broken to recover the session keys.
- **Configurable ≠ PQC-safe:** an ssl profile can advertise `X25519MLKEM768` while the actual TLS client offers only classical groups. Always verify on the wire (`make test-pqc`, OpenSSL `s_client`, or packet capture) when that distinction matters.

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
| **`X25519MLKEM768`** | Hybrid (X25519 + ML-KEM-768) | **Yes** — primary | EOS ssl profiles `EAPI`, `RADSEC`, `GNMI`, `RESTCONF`, `DOT1X`; strict peers (FreeRADIUS) |
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

NETCONF inherits SSH KEX from `management ssh`.

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
| Strict ssl profiles (`EAPI`, `RADSEC`, `GNMI`, `RESTCONF`, `DOT1X`) | **`X25519MLKEM768` only** — no classical ECDH fallback |
| FreeRADIUS RadSec | **`Groups = X25519MLKEM768`** via OpenSSL config |
| SSH management | **`mlkem768x25519-sha256`** preferred |
| SYSLOG profile | Hybrid listed **with classical fallback** (operational compromise for syslog client support) |

See [Services overview](services/index.md) for per-interface live PQC status.

## OpenSSL build requirement (lab containers)

EOS implements switch-side TLS and SSH natively. **Peer containers in this lab cannot rely on stock Alpine or Docker Hub images** for PQC-hybrid RadSec or syslog-over-TLS — those images typically link against **OpenSSL 3.3.x or older**, which does **not** negotiate `X25519MLKEM768`.

The lab therefore **self-compiles OpenSSL 3.5.7** from source and links service binaries against `/opt/openssl`.

### Shared OpenSSL base images

OpenSSL is built once per link mode in [`docker/openssl/Dockerfile`](../docker/openssl/Dockerfile) and reused by the service Dockerfiles:

| Base image | `./Configure` | Used by | Why |
|------------|---------------|---------|-----|
| `quantum-safe-openssl:3.5.7-static` | `no-shared` (`.a` archives) | `build-radius`, `build-syslog` | FreeRADIUS/syslog-ng compile against static libs so Alpine `curl-dev` pkg-config cannot pull in stock OpenSSL 3.3 |
| `quantum-safe-openssl:3.5.7-shared` | `shared` (`libssl.so`) | `build-test-runner` | curl and OpenSSH link dynamically; runtime uses `LD_LIBRARY_PATH=/opt/openssl/lib` |

Build the bases explicitly (optional — `make build-radius`, `build-syslog`, and `build-test-runner` invoke the matching base target automatically):

```bash
make build-openssl          # both static and shared (cold cache: ~4 min on arm64)
make build-openssl-static   # radius + syslog only
make build-openssl-shared   # test-runner only
```

On a warm cache, rebuilding `quantum-safe-test-runner:latest` skips the OpenSSL compile and reuses the tagged base image.

### Service images

| Image | Dockerfile | Build approach |
|-------|------------|----------------|
| `quantum-safe-radius:latest` | `docker/radius/Dockerfile` | `quantum-safe-openssl:3.5.7-static` → FreeRADIUS 3.2.6 linked against `/opt/openssl` |
| `quantum-safe-syslog:latest` | `docker/syslog/Dockerfile` | `quantum-safe-openssl:3.5.7-static` → syslog-ng 4.8.1 linked against `/opt/openssl` |
| `quantum-safe-test-runner:latest` | `docker/test-runner/Dockerfile` | `quantum-safe-openssl:3.5.7-shared` → curl 8.12 + OpenSSH 10 (PQC KEX) + gNMI/gRPC probe tools |

At runtime, radius and syslog set:

```text
OPENSSL_CONF=/etc/raddb/openssl-pqc.cnf   # radius
OPENSSL_CONF=…/openssl-pqc.cnf            # syslog (equivalent policy)
```

The test-runner sets `OPENSSL_CONF=/etc/probe/openssl-pqc.cnf` for TLS probes.

Smoke checks after build:

```bash
make build-radius       # build-openssl-static + test-radius-image
make build-syslog       # build-openssl-static + test-syslog-image
make build-test-runner  # build-openssl-shared + verify-test-runner-image
```

Each verifies `openssl list -tls-groups` includes **`X25519MLKEM768`** (and related hybrid names such as `MLKEM768` / `SecP256r1MLKEM768` where OpenSSL lists them).

!!! note "Build time and architecture"
    First build compiles OpenSSL (twice: static + shared) and each application (~minutes on a cold cache). Images are built for the **host architecture** (`amd64` / `arm64`) via `docker buildx build --load`. `make clean` removes `quantum-safe-openssl:*` along with the service images.

The **KME simulator** image (`quantum-safe-kme:latest`) uses Python/Flask TLS for ETSI QKD 014 APIs; it is built separately (`docker/kme/Dockerfile`) with lab-generated mTLS PKI — see [QKD service](services/qkd-etsi014.md).

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
make test-pqc VERBOSE=1
```

## Related

- [Services overview](services/index.md) — per-service configuration and caveats
- [Certificates and TLS 1.3](misc/certificates-and-tls13.md) — PKI requirements and OpenSSL command examples
- [PQC connectivity tests](tests/pqc.md) — handshake verification commands
- [Setup](setup.md) — build and deploy workflow
