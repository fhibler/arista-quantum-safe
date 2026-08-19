# OpenConfig connectivity tests

`make test-openconfig` runs `python -m lab.test_openconfig` against all three EOS nodes (**ceos1-both**, **ceos2-pqc**, **ceos3-qkd**) on **IPv4 and IPv6** (where the service binds dual-stack).

**Policy:** TLS 1.3 with PQC-hybrid group **`X25519MLKEM768`** on strict ssl profiles. Probes run inside **`arista-quantum-safe-test-runner`** (default `PROBE_CLIENT`) using `gnoic`, `gribic`, `gnsic`, `gnmic`, and OpenSSL.

## What is checked

Per switch, in order:

| Group | `[config]` | `[live / test-runner]` (IPv4 + IPv6 unless noted) |
|-------|------------|---------------------------------------------------|
| **gNMI** | `GNMI` ssl profile valid; `show management api gnmi` enabled | TLS + mTLS handshake; `gnmic get` hostname |
| **gNOI** | gNOI transport via gNMI / `GNMI` profile | Transport TLS; `System/Ping` RPC; reflection lists `gnoi.system.System` |
| **gRIBI** | `GRIBI` profile; listener port **9340** vrf MGMT; IPv6 `::` in bind | mTLS PQC handshake; **WARN** if wire classical KEX; `gribic get --aft IPv4` |
| **gNSI** | `GNSI` profile; `transport gnmi default` on port **6030**; certz + authz enabled | mTLS on :6030; `gnsic certz get-profile-list` (requires `-u admin`) |
| **gNPSI** | `GNPSI` profile; port **6031**; `listen-address vrf MGMT ::`; sFlow source | OpenSSL mTLS wire probe; **WARN** if classical KEX; `gnoic` reflection + `grpcurl` Subscribe (passes when sFlow active; **SKIP** only if no datagram within 8 s) |
| **RESTCONF** | `RESTCONF` profile; HTTPS transport | TLS handshake :6020 |
| **eos-sdk-rpc** | Reuses `GNMI` profile; `local interface Management0` | mTLS :9543 — **WARN** if not PQC-safe; **SKIP** IPv6 (IPv4-only bind) |

gNOI, gRIBI, gNSI, and gNPSI checks live in `lab.test_openconfig_grpc`; gNMI, RESTCONF, and eos-sdk-rpc in `lab.test_pqc_connections`.

### Tools in the test-runner image

| Tool | Used for |
|------|----------|
| `gnmic` | gNMI GET |
| `gnoic` | gNOI Ping/reflection; gNPSI reflection |
| `gribic` | gRIBI Get |
| `gnsic` | gNSI Certz.GetProfileList |
| `openssl s_client` | TLS/mTLS handshake probes (PQC via `OPENSSL_CONF`) |
| `grpcurl` | gNPSI `Subscribe` on :6031; fallback when `gnoic`/`gribic` RPC fails (rebuilt with Go 1.24+ — [Tool chain](../misc/toolchain.md)) |

Live checks use the PQC-capable clients above; see [Tool chain](../misc/toolchain.md) for build requirements.

## Pass criteria

- `[config]` profiles and listeners present for each protocol that the image supports
- Live KEX **PQC-safe** for gNMI, gNOI, gNSI Certz, and RESTCONF (`X25519MLKEM768`)
- gRIBI, gNPSI, and eos-sdk-rpc IPv4 **WARN** (not fail) when the wire is classical — see below
- eos-sdk-rpc IPv6 **SKIP** (IPv4-only bind)

## Expected SKIP / WARN

| Check | When |
|-------|------|
| gNPSI mTLS / reflection (IPv4/IPv6) | **WARN** when wire accepts classical KEX (`secp256r1`); PQC-only OpenSSL mTLS gets EOF / handshake failure |
| gNPSI Subscribe (IPv4/IPv6) | **WARN** when datagram received (inherits wire KEX on 4.36.2F); **SKIP** only when no sFlow sample within 8 s probe window |
| gRIBI IPv4/IPv6 | **WARN** when wire accepts classical KEX (`secp256r1`); PQC-only OpenSSL mTLS gets handshake failure |
| eos-sdk-rpc IPv4 | **WARN** when wire KEX is classical (`secp256r1`) despite PQC-only profile |
| eos-sdk-rpc IPv6 | **SKIP** — `local interface Management0` binds primary IPv4 only |
| gNPSI (entire section) | **SKIP** when cEOS lacks `management api gnpsi` |

## Manual reproduction

```bash
make test-openconfig
make test-openconfig VERBOSE=1
```

EOS 4.36.2F gNSI Certz requires **`transport gnmi default`** under `management api gnsi` (not `transport grpc`) and a **gRPC metadata username** on `gnsic` (`-u admin`; lab uses `username admin nopassword`):

```bash
docker exec arista-quantum-safe-test-runner gnsic -u admin -a 172.20.127.11:6030 \
  --tls-ca /etc/probe/certs/radsec-ca.pem \
  --tls-cert /etc/probe/certs/ceos1-both-client.pem \
  --tls-key /etc/probe/certs/ceos1-both-client.key \
  certz get-profile-list
```

## Result summary (EOS 4.36.2F)

Same PQC-safe values as [Test suite overview — Result summary](index.md#result-summary) for OpenConfig services:

| Service | Port | KEX used (live) | PQC-safe | Notes |
|---------|------|-----------------|----------|-------|
| gNMI | 6030 | `X25519MLKEM768` | Yes | mTLS + GET |
| gNOI | 6030 | `X25519MLKEM768` | Yes | Shared gNMI transport |
| gRIBI | 9340 | classical (`secp256r1`) | No | Suite **WARN**s; OpenSSL PQC + classical diagnostic probes |
| gNSI Certz | 6030 | `X25519MLKEM768` | Yes | Shared gNMI transport; `-u admin` |
| gNPSI (TLS) | 6031 | classical (`secp256r1`) | No | Suite **WARN**s; OpenSSL wire probe + reflection |
| gNPSI (Subscribe) | 6031 | classical (`secp256r1`) | No | Suite **WARN**s; `grpcurl` Subscribe when sFlow active |
| RESTCONF | 6020 | `X25519MLKEM768` | Yes | HTTPS |
| eos-sdk-rpc (IPv4) | 9543 | classical (`secp256r1`) | No | Suite **WARN**s; IPv4 only |

Configuration reference: [OpenConfig & gRPC](../services/openconfig.md).

See also [eAPI](eapi.md), [SSH](ssh.md), [RadSec](radsec.md), and [Syslog](syslog.md) for other management-plane checks.

<- [Test suite overview](index.md)
