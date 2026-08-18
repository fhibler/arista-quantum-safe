# Tool chain

The lab runs **PQC-hybrid-only** TLS on most EOS ssl profiles (`X25519MLKEM768` only — no classical ECDH fallback). Probe clients and peer containers must therefore negotiate hybrid key exchange on the wire, not merely “TLS 1.3 with classical groups.”

Stock Linux packages and upstream release binaries often **fail that requirement**. This page documents why the lab **rebuilds or pins** specific tool versions in [`docker/test-runner/Dockerfile`](https://github.com/fhibler/arista-quantum-safe/blob/main/docker/test-runner/Dockerfile) and the service Dockerfiles, and which clients are **[PQC-safe (live)](../pqc-overview.md#terminology)** against strict EOS profiles after those changes.

## Probe and peer client summary

**Strict** EOS ssl profiles in this lab list **`X25519MLKEM768` only** (no classical ECDH fallback). **Stock OOTB PQC-safe?** means the usual distro package or upstream release binary can complete a handshake on those profiles without lab-specific rebuilds. **Lab PQC-safe?** is the same check for the binary shipped in lab Docker images (verified or expected in `make test-*`).

| Client / component | Container | TLS stack | Stock OOTB PQC-safe? | Lab image | Lab PQC-safe? |
|--------------------|-----------|-----------|----------------------|-----------|---------------|
| **OpenSSL** (`openssl s_client`) | test-runner, radius, syslog | OpenSSL | **No** — Alpine 3.20 ≈ OpenSSL 3.3.x | Self-build **3.5.7** | **Yes** (with `OPENSSL_CONF`) |
| **curl** | test-runner | OpenSSL (linked) | **No** — links to distro OpenSSL | **8.12** + OSSL 3.5 | **Yes** |
| **OpenSSH** client | test-runner | OpenSSL (linked) | **No** — no `mlkem768x25519-sha256` in Alpine builds | **10.0** + OSSL 3.5 | **Yes** |
| **FreeRADIUS** (RadSec) | radius | OpenSSL (static) | **No** | Linked OSSL 3.5 static | **Yes** |
| **syslog-ng** (collector) | syslog | OpenSSL (static) | **No** | Linked OSSL 3.5 static | **Yes** (collector-side probe) |
| **gnmic** | test-runner | Go `crypto/tls` | **Yes** — release **0.47.0** (Go **1.25+**) | Upstream tarball | **Yes** |
| **gnoic** | test-runner | Go `crypto/tls` | **Yes** — release **0.2.1** (Go **1.24+**) | Upstream tarball | **Yes** |
| **gnsic** | test-runner | Go `crypto/tls` | **Yes** — release **0.0.4** (Go **1.24+**) | Upstream tarball | **Yes** |
| **gribic** | test-runner | Go `crypto/tls` | **No** — release **0.0.14** (Go **1.21**) | Source build **0.0.14** with Go **1.24.3** | **Yes** (rebuilt like grpcurl) |
| **grpcurl** | test-runner | Go `crypto/tls` | **No** — release built with Go **1.21** | Source build **1.9.3** with Go **1.24.3** | **Partial** — gNPSI RPCs on `:6031` work but wire KEX often classical (WARN); `:6030` handshake fails (use gnoic/gnmic/gnsic) |
| **KME simulator** | kme-a, kme-b | Python `ssl` / system OpenSSL | **No** | Stock Alpine Python | **No** — ETSI mTLS; not validated against strict PQC profiles |
| **EOS cEOS** | ceos* | Arista (native) | N/A (switch image) | Vendor image + templates | **Yes** when profile is strict (see [Services](../services/index.md) for wire exceptions) |

**Column notes**

| Column | Meaning |
|--------|---------|
| **Stock OOTB PQC-safe?** | Default upstream or Alpine package as downloaded — no lab Dockerfile changes. |
| **Lab PQC-safe?** | Negotiates hybrid **`X25519MLKEM768`** (or SSH **`mlkem768x25519-sha256`**) on the wire against the relevant lab check — not merely TLS 1.3 or hybrid listed in EOS config. |
| **Partial** | PQC-hybrid works on some listeners/ports but not all; see tool-specific sections below. |

EOS-side exceptions (config lists hybrid; wire may be classical): [Syslog](../services/syslog.md), [gRIBI / gNPSI](../services/openconfig.md#gribi-grpc), [eos-sdk-rpc](../services/openconfig.md#eos-sdk-rpc-grpc-mtls). Service-level live status: [Services overview](../services/index.md) and [Test result summary](../tests/index.md#result-summary).

## Build summary

| Component | Stock problem | Lab approach |
|-----------|---------------|--------------|
| **OpenSSL** (radius, syslog, probes) | Alpine/Docker Hub images ship OpenSSL **3.3.x or older** — no `X25519MLKEM768` | Self-build **OpenSSL 3.5.7**; link peers against `/opt/openssl` |
| **curl** | Links to system OpenSSL without PQC groups | Compile **curl 8.12** against custom OpenSSL in test-runner |
| **OpenSSH client** | No `mlkem768x25519-sha256` in distro builds | Compile **OpenSSH 10** against custom OpenSSL in test-runner |
| **grpcurl** | Upstream release built with **Go 1.21** — no PQ hybrids in `crypto/tls` | **Rebuild grpcurl 1.9.3 from source with Go 1.24+** |
| **gribic** | Upstream release built with **Go 1.21** — no PQ hybrids in `crypto/tls` | **Rebuild gribic 0.0.14 from source with Go 1.24+** |
| **gnoic / gnsic** | Go **1.24+** prebuilts OK | Pin gnoic/gnsic tarballs |
| **gnmic** | gNMI GET over mTLS | Prebuilt release (verify periodically against EOS strict profiles) |

Build entry points: `make build-openssl`, `make build-radius`, `make build-syslog`, `make build-test-runner`. Smoke checks: `make verify-test-runner-image`, plus the radius and syslog image test Makefile targets.

## OpenSSL 3.5 (peer containers)

EOS implements PQC-hybrid TLS on the switch. **FreeRADIUS, syslog-ng, curl, and OpenSSH in this lab cannot use the OpenSSL that ships with Alpine 3.20** for PQC-hybrid RadSec or syslog-over-TLS — it does not advertise `X25519MLKEM768`.

The lab compiles OpenSSL **3.5.7** once per link mode in [`docker/openssl/Dockerfile`](https://github.com/fhibler/arista-quantum-safe/blob/main/docker/openssl/Dockerfile):

| Base image | Link mode | Used by |
|------------|-----------|---------|
| `quantum-safe-openssl:3.5.7-static` | Static (`.a`) | `build-radius`, `build-syslog` |
| `quantum-safe-openssl:3.5.7-shared` | Shared (`libssl.so`) | `build-test-runner` (curl, OpenSSH, `openssl s_client`) |

Runtime policy is enforced with `OPENSSL_CONF` pointing at PQC-only group lists (for example `Groups = X25519MLKEM768` in `docker/radius/openssl-pqc.cnf`).

See also [PQC overview — OpenSSL build requirement](../pqc-overview.md#openssl-build-requirement-lab-containers) for the high-level rationale.

## Go `crypto/tls` (gRPC clients)

Go **1.24+** enables hybrid post-quantum key exchange **`X25519MLKEM768`** by default in `crypto/tls` (see [Go release notes](https://go.dev/doc/go1.24)). Go programs **ignore** `OPENSSL_CONF` — they use the Go runtime’s TLS stack only.

### grpcurl

[grpcurl](https://github.com/fullstorydev/grpcurl) release **v1.9.3** binaries on GitHub are built with **Go 1.21**. Against this lab’s strict EOS profiles they cannot complete a TLS handshake (no shared group).

The test-runner image therefore **compiles grpcurl v1.9.3 from source** with **Go 1.24.3** (`GO_VERSION` build-arg in the Dockerfile). grpcurl’s `ClientTLSConfig` does not override `CurvePreferences`, so the Go 1.24 defaults apply.

**Verified against deployed EOS (4.36.2F):** with Go **1.24.3**, grpcurl completes mTLS and gNPSI RPCs on **:6031** (reflection `list` and `gnpsi.gNPSI/Subscribe` as exercised by `make test-openconfig`). The EOS listener often negotiates **classical wire KEX** (`secp256r1`) despite the strict **`GNPSI`** profile — the suite **WARN**s (same class as gRIBI).

On the shared **gNMI/gNOI listener (:6030)**, EOS still rejects grpcurl with `tls: handshake failure` even after the Go 1.24 rebuild. **`gnoic`**, **gnmic**, and **gnsic** negotiate `X25519MLKEM768` there — use those clients for `:6030`. grpcurl remains a **fallback** for gNOI/gRIBI RPC invoke paths and the primary client for gNPSI subscribe.

Manual spot-check (lab deployed, certs mounted in test-runner):

```bash
docker exec arista-quantum-safe-test-runner grpcurl \
  -cacert /etc/probe/certs/radsec-ca.pem \
  -cert /etc/probe/certs/ceos1-both-client.pem \
  -key /etc/probe/certs/ceos1-both-client.key \
  172.20.127.11:6031 list
```

Expect `gnpsi.gNPSI` and `grpc.reflection.v1.ServerReflection`. Transport PQC on `:6030` is checked via `openssl s_client` and the Go clients above in `make test-openconfig`.

### gnoic, gribic, gnsic

These OpenConfig clients are shipped as **prebuilt** Linux tarballs from [karimra](https://github.com/karimra) releases. Current pins (`gnoic` **0.2.1**, `gnsic` **0.0.4**) are built with **Go 1.24+** and are **primary** live gRPC probes in `make test-openconfig`.

**gribic** **0.0.14** upstream tarballs are still on **Go 1.21**. The test-runner image **compiles gribic v0.0.14 from source** with **Go 1.24.3** (same approach as grpcurl). `make test-openconfig` probes PQC-hybrid mTLS on `:9340` with OpenSSL first; on EOS 4.36.2F the wire still accepts classical KEX — the suite **WARN**s (same pattern as eos-sdk-rpc) before the gRIBI Get RPC check.

### gnmic

gNMI GET uses a prebuilt **gnmic** release. Re-verify against EOS when bumping `GNMIC_VERSION` — if upstream regress to an older Go toolchain, rebuild from source the same way as grpcurl.

## What is *not* customized

| Item | Notes |
|------|-------|
| **EOS cEOS-lab** | Arista image — PQC configured via startup templates, not rebuilt here |
| **KME simulator** | Python/Flask mTLS — separate Dockerfile and lab PKI |
| **Alpine packages** | Base OS packages (Python, docker-cli, etc.) — not used for PQC TLS probes |

## Operational notes

- **`GODEBUG=tlsmlkem=0`** disables PQ hybrids in Go — do not set this in the test-runner environment.
- **`OPENSSL_CONF`** affects OpenSSL binaries only (`curl`, `openssl s_client`), not Go gRPC clients.
- After changing Dockerfile pins, run `make build-test-runner` and `make verify-test-runner-image`, then spot-check live handshakes with `make test-openconfig VERBOSE=1`.

## Related

- [Certificates and TLS 1.3](certificates-and-tls13.md) — PKI and OpenSSL command examples
- [OpenConfig & gRPC](../services/openconfig.md) — service ports and probe commands
- [OpenConfig tests](../tests/openconfig.md) — automated live check matrix
