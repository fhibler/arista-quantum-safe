# OpenConfig connectivity tests

`make test-openconfig` runs `python -m lab.test_openconfig` against all three EOS nodes (**ceos1-both**, **ceos2-pqc**, **ceos3-qkd**) on **IPv4 and IPv6** (where the service binds dual-stack).

**Policy:** TLS 1.3 with PQC-hybrid group **`X25519MLKEM768`** on strict ssl profiles. Probes run inside **`arista-quantum-safe-test-runner`** (default `PROBE_CLIENT`) using `gnoic`, `gribic`, `gnsic`, `gnmic`, and OpenSSL.

Configuration reference: [OpenConfig & gRPC](../services/openconfig.md).

## What is checked

Per switch, in order:

| Group | `[config]` | `[live / test-runner]` (IPv4 + IPv6 unless noted) |
|-------|------------|---------------------------------------------------|
| **gNMI** | `GNMI` ssl profile valid; `show management api gnmi` enabled | TLS + mTLS handshake; `gnmic get` hostname |
| **gNOI** | gNOI transport via gNMI / `GNMI` profile | Transport TLS; `System/Ping` RPC; reflection lists `gnoi.system.System` |
| **gRIBI** | `GRIBI` profile; listener port **9340** vrf MGMT; IPv6 `::` in bind | `gribic get --aft IPv4` over mTLS |
| **gNSI** | `GNSI` profile; `transport gnmi default` on port **6030**; certz + authz enabled | mTLS on :6030; `gnsic certz get-profile-list` (requires `-u admin`) |
| **gNPSI** | `GNPSI` profile; port **6031**; `listen-address vrf MGMT ::`; sFlow source | `gnoic services` mTLS; `Subscribe` RPC (**SKIP** if sFlow pipeline idle) |
| **RESTCONF** | `RESTCONF` profile; HTTPS transport | TLS handshake :6020 |
| **eos-sdk-rpc** | Reuses `GNMI` profile; `local interface Management0` | mTLS :9543 — **WARN** if not PQC-safe; **SKIP** IPv6 (IPv4-only bind) |

gNOI, gRIBI, gNSI, and gNPSI checks live in `lab.test_openconfig_grpc`; gNMI, RESTCONF, and eos-sdk-rpc in `lab.test_pqc_connections`.

## Tools in the test-runner image

| Tool | Used for |
|------|----------|
| `gnmic` | gNMI GET |
| `gnoic` | gNOI Ping/reflection; gNPSI mTLS + Subscribe |
| `gribic` | gRIBI Get |
| `gnsic` | gNSI Certz.GetProfileList |
| `openssl s_client` | TLS/mTLS handshake probes (PQC via `OPENSSL_CONF`) |

Stock `grpcurl` cannot negotiate PQC-hybrid KEX against EOS; the lab uses PQC-capable clients above.

## gNSI Certz notes

EOS 4.36.2F requires:

1. **`transport gnmi default`** under `management api gnsi` (not `transport grpc` — EOS rejects that stanza).
2. **gRPC metadata username** on `gnsic` (`-u admin`; lab uses `username admin nopassword`).

Example:

```bash
docker exec arista-quantum-safe-test-runner gnsic -u admin -a 172.20.127.11:6030 \
  --tls-ca /etc/probe/certs/radsec-ca.pem \
  --tls-cert /etc/probe/certs/ceos1-both-client.pem \
  --tls-key /etc/probe/certs/ceos1-both-client.key \
  certz get-profile-list
```

## Expected SKIP / WARN (not failures)

| Check | When |
|-------|------|
| gNPSI mTLS / Subscribe | Port not listening, reflection missing, or no sFlow datagrams within probe window on cEOS |
| eos-sdk-rpc IPv4 | **WARN** when wire KEX is classical (`secp256r1`) despite PQC-only profile |
| eos-sdk-rpc IPv6 | **SKIP** — `local interface Management0` binds primary IPv4 only |

## Run commands

```bash
make test-openconfig
make test-openconfig VERBOSE=1
make test-lab          # includes test-openconfig after test-pqc
```

## Result summary (EOS 4.36.2F)

| Service | Port | Live PQC (expected) | Notes |
|---------|------|---------------------|-------|
| gNMI | 6030 | Yes | mTLS + GET |
| gNOI | 6030 | Yes | Shared gNMI transport |
| gRIBI | 9340 | Yes | Dedicated listener |
| gNSI Certz | 6030 | Yes | Shared gNMI transport; `-u admin` |
| gNPSI TLS | 6031 | Yes | Dedicated listener; dual-stack bind |
| gNPSI Subscribe | 6031 | SKIP common | sFlow-dependent on cEOS |
| RESTCONF | 6020 | Yes | HTTPS |
| eos-sdk-rpc | 9543 | No (WARN) | IPv4 only |

See also [PQC connectivity](pqc.md) for eAPI, SSH, RadSec, and syslog checks (`make test-pqc`).
