# OpenConfig & gRPC

This page covers **gNMI**, **gNOI** (same gRPC transport), **RESTCONF**, and **eos-sdk-rpc** TLS configuration on cEOS 4.36.1F.

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

gNOI uses the same gRPC endpoint and ssl profile as gNMI.

### Caveats

| Topic | Status on cEOS 4.36.1F |
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

| Topic | Status on cEOS 4.36.1F |
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

### Caveats

| Topic | Status on cEOS 4.36.1F |
|-------|------------------------|
| Config | Profile lists `X25519MLKEM768` |
| Live wire | **Not PQC-safe** — often negotiates classical group or fails PQC-only probe |

!!! warning "Known cEOS 4.36.1F gap"
    Configuration lists `X25519MLKEM768`, but live handshakes on port **9543** often **fail PQC negotiation**:

    - PQC-only OpenSSL client → EOF / no handshake
    - Permissive client → TLS 1.3 with classical group (e.g. `secp256r1`)

    `make test-pqc` validates `[config]` and reports **`WARN`** on the live probe instead of failing the suite.

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

PQC-only probe (may fail on 4.36.1F):

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

## Summary

| Service | Port | Profile | Live PQC on 4.36.1F |
|---------|------|---------|---------------------|
| gNMI / gNOI | 6030 | GNMI | Yes |
| RESTCONF | 6020 | RESTCONF | Yes |
| eos-sdk-rpc | 9543 | GNMI | **No** (config OK; wire gap) |

Automated checks: `make test-pqc`. Details: [PQC tests](../tests/pqc.md).

<- [Services overview](index.md)
