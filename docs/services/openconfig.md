# OpenConfig & gRPC

This page covers **gNMI**, **gNOI** (same gRPC transport), **gRIBI**, **gNSI**, **gNPSI**, **RESTCONF**, and **eos-sdk-rpc** TLS configuration on EOS.

Live checks: **`make test-openconfig`** ([test matrix](../tests/openconfig.md)).

| Item | Value |
|------|-------|
| Template | `configs/ceos/ceos*.cfg.in` → `lab/.gen/` |
| Shared policy | TLS **1.3 only**, PQC-hybrid group **`X25519MLKEM768`**, AEAD ciphers |
| Certificates | Classical RSA with SANs for each switch MGMT address (`make gen-topo`) |

See also [Certificates and TLS 1.3](../misc/certificates-and-tls13.md).

All services below use **VRF MGMT** unless noted.

---

## gNMI / gNOI (gRPC)

| Item | Value |
|------|-------|
| Port | **6030** |
| Profile | `GNMI` |
| mTLS | Client cert signed by lab CA (`radsec-ca.pem` trust on switch) |

### Configuration

#### SSL profile `GNMI`

Complete profile from `configs/ceos/ceos1-both.cfg.in`:

```text
management security
   ssl profile GNMI
      tls versions 1.3
      key-establishment-group X25519MLKEM768
      cipher v1.3 TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256
      certificate ceos1-both-gnmi.pem key ceos1-both-gnmi.key
      trust certificate radsec-ca.pem
```

#### Service binding

```text
management api gnmi
   transport grpc default
      vrf MGMT
      ssl profile GNMI
```

gNOI uses the same gRPC endpoint and ssl profile as gNMI. **`make test-openconfig`** reports **separate gNOI check lines** (transport TLS, `System/Ping` RPC, gRPC reflection) so agent-level PQC regressions are visible even when gNMI GET passes.

### gNOI-specific verification

gRPC reflection (expects `gnoi.system.System`):

```bash
docker exec arista-quantum-safe-test-runner gnoic -a 172.20.127.11:6030 \
  --tls-ca /etc/probe/certs/radsec-ca.pem \
  --tls-cert /etc/probe/certs/ceos1-both-client.pem \
  --tls-key /etc/probe/certs/ceos1-both-client.key \
  --tls-version 1.3 services
```

Primary live gRPC probes use **gnoic**, **gribic**, **gnmic**, and **gnsic** (Go **1.24+**, PQC-hybrid `crypto/tls`) on **:6030**. **grpcurl** is rebuilt with Go **1.24+** in the test-runner image for **gNPSI :6031** and as an RPC **fallback** when primary clients fail — see [Tool chain](../misc/toolchain.md#grpcurl).

`System/Ping` over mTLS (`gnoic`):

```bash
docker exec arista-quantum-safe-test-runner gnoic -a 172.20.127.11:6030 \
  --tls-ca /etc/probe/certs/radsec-ca.pem \
  --tls-cert /etc/probe/certs/ceos1-both-client.pem \
  --tls-key /etc/probe/certs/ceos1-both-client.key \
  --tls-version 1.3 system ping --destination 127.0.0.1 --count 1 --do-not-resolve
```

---

### Caveats

| Topic | Status on EOS |
|-------|------------------------|
| Config | Profile valid; PQC-hybrid only |
| Live TLS | **PQC-safe** |
| Live mTLS | **PQC-safe** with lab client cert |

### Verification

#### Configuration

```bash
docker exec -i arista-quantum-safe-ceos1-both Cli <<'EOF'
enable
show management security ssl profile GNMI detail
show management api gnmi
EOF
```

#### Live PQC handshake

TLS (server auth only):

```bash
docker exec arista-quantum-safe-test-runner sh -c \
  'OPENSSL_CONF=/etc/probe/openssl-pqc.cnf \
   openssl s_client -connect 172.20.127.11:6030 -tls1_3 \
   -CAfile /etc/probe/certs/radsec-ca.pem -brief </dev/null 2>&1' \
  | grep -E 'Protocol|Negotiated TLS1.3 group'
```

mTLS (client cert per switch, e.g. ceos1-both):

```bash
docker exec arista-quantum-safe-test-runner sh -c \
  'OPENSSL_CONF=/etc/probe/openssl-pqc.cnf \
   openssl s_client -connect 172.20.127.11:6030 -tls1_3 \
   -CAfile /etc/probe/certs/radsec-ca.pem \
   -cert /etc/probe/certs/ceos1-both-client.pem \
   -key /etc/probe/certs/ceos1-both-client.key \
   -brief </dev/null 2>&1' \
  | grep -E 'Protocol|Negotiated TLS1.3 group'
```

---

## RESTCONF (HTTPS)

| Item | Value |
|------|-------|
| Port | **6020** |
| Profile | `RESTCONF` |

### Configuration

#### SSL profile `RESTCONF`

Complete profile from `configs/ceos/ceos1-both.cfg.in` (reuses gNMI server cert on each switch):

```text
management security
   ssl profile RESTCONF
      tls versions 1.3
      key-establishment-group X25519MLKEM768
      cipher v1.3 TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256
      certificate ceos1-both-gnmi.pem key ceos1-both-gnmi.key
      trust certificate radsec-ca.pem
```

#### Service binding

```text
management api restconf
   transport https restconf
      ssl profile RESTCONF
   vrf MGMT
```

### Caveats

| Topic | Status on EOS |
|-------|------------------------|
| Config | Profile valid; PQC-hybrid only |
| Live wire | **PQC-safe** |

### Verification

#### Configuration

```bash
docker exec -i arista-quantum-safe-ceos1-both Cli <<'EOF'
enable
show management security ssl profile RESTCONF detail
show management api restconf
EOF
```

#### Live PQC handshake

```bash
docker exec arista-quantum-safe-test-runner sh -c \
  'OPENSSL_CONF=/etc/probe/openssl-pqc.cnf \
   openssl s_client -connect 172.20.127.11:6020 -tls1_3 \
   -CAfile /etc/probe/certs/radsec-ca.pem -brief </dev/null 2>&1' \
  | grep -E 'Protocol|Negotiated TLS1.3 group'
```

---

## eos-sdk-rpc (gRPC mTLS)

| Item | Value |
|------|-------|
| Port | **9543** |
| Profile | `GNMI` (reused) |
| Auth | mTLS |

### Configuration

#### SSL profile

Reuses the complete **`GNMI`** ssl profile (see [gNMI](#gnmi-gnoi-grpc)).

#### Service binding

Complete stanza from `configs/ceos/ceos1-both.cfg.in`:

```text
management api eos-sdk-rpc
   transport grpc default
      local interface Management0
      service all
      no disabled
      ssl profile GNMI
```

Unlike gNMI, eos-sdk-rpc uses **`local interface Management0`** rather than **`vrf MGMT`**. Arista binds the gRPC server to the interface **primary IPv4 address** — not dual-stack. `show management api eos-sdk-rpc` reports:

```text
Listening on:
   Local interface:
      Management0, IP address is 172.20.127.11
      port: 9543, VRF: MGMT
```

gNMI on the same **`GNMI`** ssl profile listens on **`::`** (IPv4 + IPv6) when configured with `vrf MGMT`.

### Caveats

| Topic | Status on EOS |
|-------|------------------------|
| Config | Profile lists `X25519MLKEM768` |
| IPv4 live wire | **Not PQC-safe** — PQC-only probe EOF; explicit `secp256r1` client completes TLS 1.3 |
| IPv6 live wire | **No listener** — `local interface Management0` binds IPv4 only; `make test-openconfig` **SKIP**s IPv6 |

!!! note "IPv6 limitation (binding model)"
    **Not an ACL issue.** Control-plane ACLs permit TCP **9543** on both IPv4 and IPv6. Management0 has an IPv6 address, but eos-sdk-rpc does not listen on it because the transport is bound via **`local interface Management0`**, which resolves to the primary IPv4. There is no equivalent of gNMI's **`vrf MGMT`** dual-stack listener for eos-sdk-rpc in this lab config.

!!! warning "Known EOS gap — eos-sdk-rpc"
    Configuration lists `X25519MLKEM768`, but live handshakes on port **9543** often **fail PQC negotiation** on IPv4:

    - PQC-only OpenSSL client → EOF / no handshake
    - Explicit `-groups secp256r1` → TLS 1.3 with classical KEX (diagnostic / `make test-openconfig` fallback)

    `make test-openconfig` validates `[config]` and reports **`WARN`** on the IPv4 live probe instead of failing the suite. IPv6 live probes are **`SKIP`**ped.

### Verification

#### Configuration

```bash
docker exec -i arista-quantum-safe-ceos1-both Cli <<'EOF'
enable
show management security ssl profile GNMI detail
show management api eos-sdk-rpc
EOF
```

#### Live PQC handshake

PQC-only probe (may fail on some EOS builds):

```bash
docker exec arista-quantum-safe-test-runner sh -c \
  'OPENSSL_CONF=/etc/probe/openssl-pqc.cnf \
   openssl s_client -connect 172.20.127.11:9543 -tls1_3 \
   -CAfile /etc/probe/certs/radsec-ca.pem \
   -cert /etc/probe/certs/ceos1-both-client.pem \
   -key /etc/probe/certs/ceos1-both-client.key \
   -brief </dev/null 2>&1'
```

Compare with a classical-tolerant client (diagnostic only):

```bash
docker exec arista-quantum-safe-test-runner sh -c \
  'openssl s_client -connect 172.20.127.11:9543 -tls1_3 \
   -CAfile /etc/probe/certs/radsec-ca.pem \
   -cert /etc/probe/certs/ceos1-both-client.pem \
   -key /etc/probe/certs/ceos1-both-client.key \
   -brief </dev/null 2>&1' \
  | grep -E 'Protocol|Negotiated TLS1.3 group'
```

---

## gRIBI (gRPC)

| Item | Value |
|------|-------|
| Port | **9340** |
| Profile | `GRIBI` (dedicated; reuses gNMI cert/key files) |
| Transport | `vrf MGMT` (dual-stack) |

### Configuration

```text
management security
   ssl profile GRIBI
      tls versions 1.3
      key-establishment-group X25519MLKEM768
      cipher v1.3 TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256
      certificate ceos1-both-gnmi.pem key ceos1-both-gnmi.key
      trust certificate radsec-ca.pem
!
management api gribi
   transport grpc default
      vrf MGMT
      ssl profile GRIBI
```

### Caveats

| Topic | Status on EOS 4.36.2F |
|-------|------------------------|
| Config | Profile valid; PQC-hybrid only (`X25519MLKEM768`) |
| Live TLS | **Not PQC-safe** — wire accepts classical KEX (`secp256r1`); PQC-only clients get `handshake failure` |
| Probe client | **gribic** rebuilt with Go **1.24+** in the test-runner image ([Tool chain](../misc/toolchain.md#gnoic-gribic-gnsic)) |

!!! warning "Known EOS gap — gRIBI"
    Configuration lists `X25519MLKEM768`, but live handshakes on port **9340** negotiate classical KEX (`secp256r1`) on EOS 4.36.2F. PQC-only clients get `handshake failure`.

    `make test-openconfig` validates `[config]` and runs OpenSSL probes that try PQC-hybrid mTLS first, then fall back to an explicit **`secp256r1`** diagnostic. The live probe **WARN**s instead of failing the suite (same class of issue as [eos-sdk-rpc](#eos-sdk-rpc-grpc-mtls)).

### Verification

```bash
docker exec -i arista-quantum-safe-ceos1-both Cli <<'EOF'
enable
show management security ssl profile GRIBI detail
show management api gribi
EOF

docker exec arista-quantum-safe-test-runner gribic -a 172.20.127.11:9340 \
  --tls-ca /etc/probe/certs/radsec-ca.pem \
  --tls-cert /etc/probe/certs/ceos1-both-client.pem \
  --tls-key /etc/probe/certs/ceos1-both-client.key \
  get --aft IPv4
```

---

## gNSI (gRPC)

| Item | Value |
|------|-------|
| Port | **6030** (shared gNMI listener) |
| Profile | `GNSI` (dedicated ssl profile; wire TLS uses **`GNMI`** on :6030) |
| Services | `certz`, `authz` |
| Transport | `transport gnmi default` (not `transport grpc`) |

The lab defines a dedicated **`GNSI`** ssl profile under `management security` (PQC-hybrid-only, mTLS trust). Certz/Authz RPCs register on the gNMI listener when bound with **`transport gnmi default`**.

### Configuration

```text
management security
   ssl profile GNSI
      tls versions 1.3
      key-establishment-group X25519MLKEM768
      cipher v1.3 TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256
      certificate ceos1-both-gnmi.pem key ceos1-both-gnmi.key
      trust certificate radsec-ca.pem
!
management api gnsi
   transport gnmi default
   service authz
   service certz
```

EOS 4.36.2F **rejects** `transport grpc default` under `management api gnsi` (the stanza is dropped from startup-config). Use **`transport gnmi default`** instead.

### Verification

**Certz is not advertised in gRPC reflection**; use **`gnsic`** with mTLS **and** gRPC metadata username (`admin`, nopassword in the lab):

```bash
docker exec arista-quantum-safe-test-runner gnsic -u admin -a 172.20.127.11:6030 \
  --tls-ca /etc/probe/certs/radsec-ca.pem \
  --tls-cert /etc/probe/certs/ceos1-both-client.pem \
  --tls-key /etc/probe/certs/ceos1-both-client.key \
  certz get-profile-list
```

Port is read from `show management api gnsi | json` (`transports.default.port`, typically **6030**).

---

## gNPSI (gRPC / sFlow proxy)

| Item | Value |
|------|-------|
| Port | **6031** (lab-chosen; CP-ACL permits it) |
| Profile | `GNPSI` (dedicated) |
| Source | sFlow |

gNPSI proxies sFlow samples to gRPC clients. Requires sFlow enabled on at least one interface. Unlike gRIBI/gNMI (which use `vrf MGMT` on the transport), gNPSI binds the listen socket with **`listen-address vrf MGMT`** — `vrf MGMT` alone is not accepted under `management api gnpsi transport grpc`. Only **one** `listen-address` is permitted; **`listen-address vrf MGMT ::`** dual-stacks IPv4 and IPv6 on MGMT.

### Configuration

```text
management security
   ssl profile GNPSI
      tls versions 1.3
      key-establishment-group X25519MLKEM768
      cipher v1.3 TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256
      certificate ceos1-both-gnmi.pem key ceos1-both-gnmi.key
      trust certificate radsec-ca.pem
!
management api gnpsi
   transport grpc default
      listen-address vrf MGMT ::
      port 6031
      ssl profile GNPSI
      source sFlow
      no disabled
!
interface Ethernet8
   sflow enable
!
sflow run
sflow interface egress enable default Ethernet8
```

Ingress sampling is enabled under `interface Ethernet8` (`sflow enable`) — the L3 routed port towards each Alpine host (`host1`/`host2`/`host3`). Egress sampling on the same interface captures switch-to-host traffic. On a deployed lab, sampled interfaces usually carry enough traffic for **`grpcurl` Subscribe** to receive datagrams during **`make test-openconfig`** (IPv4 and IPv6). If Subscribe **SKIP**s (no sample within 8 s), run **`make test-hosts`** or ping across a sampled link and retry.

### Caveats

| Topic | Status on EOS |
|-------|----------------|
| Config | Dedicated `GNPSI` profile; PQC-hybrid only |
| Live TLS / mTLS | **Not PQC-safe** on 4.36.2F — wire accepts classical KEX (`secp256r1`); PQC-only clients get EOF / handshake failure (same class as [gRIBI](#gribi-grpc)) |
| Subscribe live | **`grpcurl` Subscribe** receives sFlow datagrams on IPv4 and IPv6 when host traffic is present; `make test-openconfig` reports **WARN** (classical wire KEX on 4.36.2F) or **SKIP** only when no sample within the 8 s probe window |

!!! warning "Known EOS gap — gNPSI"
    Configuration lists `X25519MLKEM768`, but live handshakes on port **6031** negotiate classical KEX (`secp256r1`) on EOS 4.36.2F. PQC-only clients get EOF / handshake failure.

    `make test-openconfig` validates `[config]` and reports **`WARN`** on the live wire probe instead of failing the suite. Subscribe RPC tests are independent of KEX and still **PASS** when sFlow samples are present.

### Verification

#### Configuration

```bash
docker exec -i arista-quantum-safe-ceos1-both Cli <<'EOF'
enable
show management security ssl profile GNPSI detail
show management api gnpsi
EOF
```

#### Live PQC mTLS and Subscribe

mTLS + gRPC reflection (`gnoic`):

```bash
docker exec arista-quantum-safe-test-runner gnoic -a 172.20.127.11:6031 \
  --tls-ca /etc/probe/certs/radsec-ca.pem \
  --tls-cert /etc/probe/certs/ceos1-both-client.pem \
  --tls-key /etc/probe/certs/ceos1-both-client.key \
  --tls-version 1.3 services
```

`Subscribe` RPC (`grpcurl`; expects `gnpsi.gNPSI`):

```bash
docker exec arista-quantum-safe-test-runner grpcurl \
  -cacert /etc/probe/certs/radsec-ca.pem \
  -cert /etc/probe/certs/ceos1-both-client.pem \
  -key /etc/probe/certs/ceos1-both-client.key \
  -d '{}' '172.20.127.11:6031' gnpsi.gNPSI/Subscribe
```

---

## Summary

| Service | Port | Profile | Live PQC | `make test-openconfig` |
|---------|------|---------|----------|------------------------|
| gNMI | 6030 | `GNMI` | Yes | TLS, mTLS, GET |
| gNOI | 6030 (shared) | `GNMI` | Yes | Ping RPC, reflection |
| gRIBI | 9340 | `GRIBI` | **No** (WARN on 4.36.2F) | mTLS + Get |
| gNSI | 6030 (via `transport gnmi default`) | `GNSI` profile; wire TLS on `GNMI` | Yes | Certz.GetProfileList (`-u admin`) |
| gNPSI | 6031 | `GNPSI` | **No** (WARN on 4.36.2F) | mTLS wire probe, reflection, Subscribe (IPv4 + IPv6) |
| RESTCONF | 6020 | `RESTCONF` | Yes | HTTPS handshake |
| eos-sdk-rpc | 9543 | `GNMI` (reused) | **No** (WARN on IPv4) | mTLS; SKIP IPv6 |

Automated checks: **`make test-openconfig`**. Test matrix: [OpenConfig tests](../tests/openconfig.md). Related: [eAPI](../tests/eapi.md), [SSH](../tests/ssh.md), [RadSec](../tests/radsec.md).

<- [Services overview](index.md)
