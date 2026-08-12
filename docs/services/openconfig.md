# OpenConfig & gRPC

This page covers **gNMI**, **gNOI** (same gRPC transport), **RESTCONF**, **eos-sdk-rpc**, and related TLS configuration on cEOS 4.36.1F.

## Shared TLS model

EOS management APIs use named **ssl profiles** under `management security`:

- TLS **1.3 only**
- Single PQC-hybrid group: **`X25519MLKEM768`**
- AEAD ciphers: `TLS_AES_256_GCM_SHA384`, `TLS_CHACHA20_POLY1305_SHA256`, `TLS_AES_128_GCM_SHA256`

Certificates are classical RSA with SANs for each switch MGMT address (`make gen-topo`).

---

## gNMI / gNOI (gRPC)

| Item | Value |
|------|-------|
| Port | **6030** |
| Profile | `GNMI` |
| VRF | MGMT |
| mTLS | Client cert signed by lab CA (`radsec-ca.pem` trust on switch for gNMI clients) |

```text
management api gnmi
   transport grpc default
      vrf MGMT
      ssl profile GNMI
```

### Caveats (gNMI)

| Topic | Status on cEOS 4.36.1F |
|-------|------------------------|
| Config | Profile valid; PQC-hybrid only |
| Live TLS | **PQC-safe** |
| Live mTLS | **PQC-safe** with lab client cert |

### Verification (gNMI)

TLS (server auth only):

```bash
docker exec arista-quantum-safe-radius sh -c \
  'OPENSSL_CONF=/etc/raddb/openssl-pqc.cnf \
   openssl s_client -connect 172.20.127.11:6030 -tls1_3 \
   -CAfile /etc/raddb/certs/radsec/ca.pem -brief </dev/null 2>&1' \
  | grep -E 'Protocol|Negotiated TLS1.3 group'
```

mTLS (client cert per switch, e.g. ceos1-both):

```bash
docker exec arista-quantum-safe-radius sh -c \
  'OPENSSL_CONF=/etc/raddb/openssl-pqc.cnf \
   openssl s_client -connect 172.20.127.11:6030 -tls1_3 \
   -CAfile /etc/raddb/certs/radsec/ca.pem \
   -cert /etc/raddb/certs/radsec/ceos1-both-gnmi.pem \
   -key /etc/raddb/certs/radsec/ceos1-both-gnmi.key \
   -brief </dev/null 2>&1' \
  | grep -E 'Protocol|Negotiated TLS1.3 group'
```

gNOI uses the same gRPC endpoint and ssl profile as gNMI.

---

## RESTCONF (HTTPS)

| Item | Value |
|------|-------|
| Port | **6020** |
| Profile | `RESTCONF` |
| VRF | MGMT |

```text
management api restconf
   transport https restconf
      ssl profile RESTCONF
   vrf MGMT
```

### Caveats (RESTCONF)

| Topic | Status on cEOS 4.36.1F |
|-------|------------------------|
| Config | Profile valid; PQC-hybrid only |
| Live wire | **PQC-safe** |

### Verification (RESTCONF)

```bash
docker exec arista-quantum-safe-radius sh -c \
  'OPENSSL_CONF=/etc/raddb/openssl-pqc.cnf \
   openssl s_client -connect 172.20.127.11:6020 -tls1_3 \
   -CAfile /etc/raddb/certs/radsec/ca.pem -brief </dev/null 2>&1' \
  | grep -E 'Protocol|Negotiated TLS1.3 group'
```

---

## eos-sdk-rpc (gRPC mTLS)

| Item | Value |
|------|-------|
| Port | **9543** |
| Profile | `GNMI` (reused) |
| Auth | mTLS |

```text
management api eos-sdk-rpc
   transport grpc default
      ssl profile GNMI
```

### Caveats (eos-sdk-rpc)

!!! warning "Known cEOS 4.36.1F gap"
    Configuration lists `X25519MLKEM768`, but live handshakes on port **9543** often **fail PQC negotiation**:

    - PQC-only OpenSSL client -> EOF / no handshake
    - Permissive client -> TLS 1.3 with classical group (e.g. `secp256r1`)

    `make test-pqc` validates `[config]` and reports **`WARN`** on the live probe instead of failing the suite.

### Verification (eos-sdk-rpc)

PQC-only probe (may fail on 4.36.1F):

```bash
docker exec arista-quantum-safe-radius sh -c \
  'OPENSSL_CONF=/etc/raddb/openssl-pqc.cnf \
   openssl s_client -connect 172.20.127.11:9543 -tls1_3 \
   -CAfile /etc/raddb/certs/radsec/ca.pem \
   -cert /etc/raddb/certs/radsec/ceos1-both-gnmi.pem \
   -key /etc/raddb/certs/radsec/ceos1-both-gnmi.key \
   -brief </dev/null 2>&1'
```

Compare with a classical-tolerant client (diagnostic only):

```bash
docker exec arista-quantum-safe-radius sh -c \
  'openssl s_client -connect 172.20.127.11:9543 -tls1_3 \
   -CAfile /etc/raddb/certs/radsec/ca.pem \
   -cert /etc/raddb/certs/radsec/ceos1-both-gnmi.pem \
   -key /etc/raddb/certs/radsec/ceos1-both-gnmi.key \
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
