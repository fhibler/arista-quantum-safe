# Certificates and TLS 1.3

This page describes **what certificates must contain** for TLS 1.3 services in the Quantum Safe lab, and how to generate or inspect them with OpenSSL. PQC applies to **key establishment** (TLS 1.3 groups such as `X25519MLKEM768`); **certificates and signatures stay classical** (RSA or ECDSA in this lab).

## Lab PKI overview

| Item | Location | Notes |
|------|----------|-------|
| Generation | `lab/gen_pki.py` via `make gen-topo` | CA, RadSec server, per-switch client/eAPI/gNMI certs, syslog collector cert |
| Output | `lab/.gen/pki/` | Bind-mounted into containers and EOS `flash:` |
| Install on EOS | Containerlab post-boot exec | `copy flash:… certificate:` / `sslkey:` (exec-only — not in startup-config) |
| Lab CA subject | `/CN=quantum-safe-radsec-ca/O=Lab/C=US` | Also written as `radsec-ca.pem` |
| Validity | 825 days | Lab default in `gen_pki.py` |

KME mTLS material for QKD is generated separately by `lab/gen_kme_pki.py` into `lab/.gen/kme-pki/`. See [QKD / ETSI 014](../services/qkd-etsi014.md).

## TLS 1.3 certificate requirements

TLS 1.3 uses certificates only for **authentication** (server identity, optional client identity). Key exchange is negotiated separately via **key-establishment groups** configured in EOS ssl profiles or OpenSSL `Groups` — not in the X.509 certificate.

### Server certificate (EOS or peer server)

Required for services where the switch or collector **terminates TLS** (eAPI, gNMI, RESTCONF, RadSec server, syslog-ng).

| Field / extension | Requirement | Lab example |
|-------------------|-------------|-------------|
| Key type | RSA or ECDSA (classical) | RSA 2048-bit |
| `subjectAltName` | **Must include** the IP or DNS name clients use to connect | `IP:172.20.127.11`, `DNS:ceos1-both` |
| `extendedKeyUsage` | `serverAuth` | Required for TLS server role |
| `keyUsage` | `digitalSignature`, `keyEncipherment` (RSA) | Set in `gen_pki.py` extensions |
| CA chain | Issued by a CA trusted by the client | Lab CA `radsec-ca.pem` |
| TLS version | Certificate algorithm is independent of TLS version | Pair with **TLS 1.3 only** policy on the listener |

EOS ssl profile binding (server role):

```text
management security
   ssl profile EAPI
      tls versions 1.3
      key-establishment-group X25519MLKEM768
      cipher v1.3 TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256
      certificate ceos1-both-eapi.pem key ceos1-both-eapi.key
```

### Client certificate (mTLS)

Required when the **remote party verifies the client** (RadSec, gNMI mTLS, EAP-TLS supplicant, eos-sdk-rpc).

| Field / extension | Requirement | Lab example |
|-------------------|-------------|-------------|
| Key type | RSA or ECDSA (classical) | RSA 2048-bit |
| `subjectAltName` or CN | Identifies the client to the server | `CN=ceos1-both`, `DNS:ceos2-pqc` |
| `extendedKeyUsage` | `clientAuth` | Required for TLS client role |
| `keyUsage` | `digitalSignature` | Client authentication |
| Trust on EOS | CA in ssl profile | `trust certificate radsec-ca.pem` |

EOS ssl profile binding (client role):

```text
management security
   ssl profile RADSEC
      tls versions 1.3
      key-establishment-group X25519MLKEM768
      cipher v1.3 TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256
      certificate ceos1-both-client.pem key ceos1-both-client.key
      trust certificate radsec-ca.pem
```

### What certificates do **not** control

- **PQC-hybrid key exchange** — configured via `key-establishment-group` (EOS) or OpenSSL `Groups` (peers), not embedded in the cert
- **TLS 1.3 AEAD ciphers** — configured via `cipher v1.3 …` (EOS) or `CipherString` (OpenSSL)
- **SSH host keys** — separate from X.509; SSH uses `management ssh` KEX, not ssl profiles

## OpenSSL command examples

Replace paths and subjects for your environment. The lab uses RSA 2048 and a single lab CA.

### Create a lab CA

```bash
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout ca.key -out ca.pem -days 825 \
  -subj "/CN=quantum-safe-radsec-ca/O=Lab/C=US"
```

### Server certificate (TLS 1.3 server)

```bash
# Private key + CSR
openssl req -newkey rsa:2048 -nodes \
  -keyout server.key -out server.csr \
  -subj "/CN=ceos1-both/O=Lab/C=US"

# Extensions: SAN must match the address clients connect to
cat > server.ext <<'EOF'
subjectAltName = IP:172.20.127.11,IP:2001:db8:127::11,DNS:ceos1-both
extendedKeyUsage = serverAuth
keyUsage = digitalSignature,keyEncipherment
EOF

openssl x509 -req -in server.csr -CA ca.pem -CAkey ca.key -CAcreateserial \
  -out server.pem -days 825 -extfile server.ext

# EOS expects separate cert and key files (PEM)
cp server.pem ceos1-both-eapi.pem
cp server.key ceos1-both-eapi.key
```

### Client certificate (TLS 1.3 mTLS client)

```bash
openssl req -newkey rsa:2048 -nodes \
  -keyout client.key -out client.csr \
  -subj "/CN=ceos1-both/O=Lab/C=US"

cat > client.ext <<'EOF'
subjectAltName = DNS:ceos1-both
extendedKeyUsage = clientAuth
keyUsage = digitalSignature
EOF

openssl x509 -req -in client.csr -CA ca.pem -CAkey ca.key -CAcreateserial \
  -out client.pem -days 825 -extfile client.ext
```

### Inspect a certificate

```bash
openssl x509 -in server.pem -noout -text | grep -E 'Subject:|DNS:|IP Address:|Extended Key Usage'
openssl verify -CAfile ca.pem server.pem
```

### Test TLS 1.3 server handshake (PQC-hybrid group)

Requires OpenSSL 3.5+ with ML-KEM support (lab **test-runner** image):

```bash
# Server auth only (eAPI-style)
OPENSSL_CONF=/etc/probe/openssl-pqc.cnf \
openssl s_client -connect 172.20.127.11:443 -tls1_3 \
  -CAfile /etc/probe/certs/radsec-ca.pem -brief </dev/null 2>&1 \
  | grep -E 'Protocol|Negotiated TLS1.3 group'
```

Expected on a PQC-enabled path:

```text
Protocol version: TLSv1.3
Negotiated TLS1.3 group: X25519MLKEM768
```

### Test TLS 1.3 mTLS client handshake

```bash
# RadSec / gNMI mTLS-style
OPENSSL_CONF=/etc/probe/openssl-pqc.cnf \
openssl s_client -connect 172.20.127.50:2083 -tls1_3 \
  -CAfile /etc/probe/certs/radsec-ca.pem \
  -cert /etc/probe/certs/ceos1-both-client.pem \
  -key /etc/probe/certs/ceos1-both-client.key \
  -brief </dev/null 2>&1 \
  | grep -E 'Protocol|Negotiated TLS1.3 group|Verify return code'
```

A successful mTLS probe shows `Verify return code: 0 (ok)` and the negotiated PQC-hybrid group when both sides support it.

### OpenSSL peer policy (non-EOS servers)

Lab peers pin TLS 1.3 and groups via `OPENSSL_CONF`. Example for strict PQC-only (FreeRADIUS):

```ini
[system_default_sect]
Groups = X25519MLKEM768
CipherString = TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256
MinProtocol = TLSv1.3
MaxProtocol = TLSv1.3
```

See `docker/radius/openssl-pqc.cnf` and `docker/syslog/openssl-pqc.cnf`.

## Installing certificates on EOS

Startup-config references certificate **filenames** in ssl profiles. Files are copied after boot (Containerlab exec), for example:

```text
copy flash:ceos1-both-eapi.pem certificate:ceos1-both-eapi.pem
copy flash:ceos1-both-eapi.key sslkey:ceos1-both-eapi.key
copy flash:radsec-ca.pem certificate:radsec-ca.pem
```

Verify installation:

```bash
docker exec -i arista-quantum-safe-ceos1-both Cli <<'EOF'
enable
show management security ssl profile EAPI detail
EOF
```

Expect `State: valid` and the configured certificate name.

## Per-service mapping

| Service | Server cert on | Client cert on | CA trust |
|---------|----------------|----------------|----------|
| eAPI | EOS (`*-eapi.pem`) | Not required (local `admin` auth) | Optional on client |
| gNMI / RESTCONF | EOS (`*-gnmi.pem`) | Probe / SDK clients (`*-client.pem`) | `radsec-ca.pem` on switch |
| RadSec | FreeRADIUS (`server.pem`) | EOS (`*-client.pem`) | Both sides trust lab CA |
| Syslog | syslog-ng (`server.pem`) | EOS (`*-client.pem`) | Both sides trust lab CA |
| EAP-TLS (802.1X) | FreeRADIUS EAP module | EOS supplicant (`DOT1X` profile) | `radsec-ca.pem` on supplicant |

Detailed ssl profiles and service bindings: [Services overview](../services/index.md).

<- [Miscellaneous](index.md)
