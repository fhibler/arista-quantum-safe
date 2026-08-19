# eAPI

eAPI is served over **HTTPS / TLS 1.3** on port **443** in VRF MGMT, bound to ssl profile **`EAPI`**.

| Item | Value |
|------|-------|
| Port | **443** (HTTPS) |
| Profile | `EAPI` |
| KEX group | `X25519MLKEM768` only (no classical fallback) |
| Template | `configs/ceos/ceos*.cfg.in` → `lab/.gen/` |
| JSON-RPC | `https://<mgmt-ip>:443/command-api` |
| Certificates | Per-switch server cert (`*-eapi.pem` / `*-eapi.key`) from `make gen-topo` |

See also [Certificates and TLS 1.3](../misc/certificates-and-tls13.md).

## Configuration

### SSL profile `EAPI`

Complete profile from `configs/ceos/ceos1-both.cfg.in` (per-switch cert names differ):

```text
management security
   ssl profile EAPI
      tls versions 1.3
      key-establishment-group X25519MLKEM768
      cipher v1.3 TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256
      certificate ceos1-both-eapi.pem key ceos1-both-eapi.key
```

PKI is installed post-boot via Containerlab exec (`copy flash:…`); filenames are referenced in startup-config only.

### Service binding

```text
management api http-commands
   no shutdown
   protocol https ssl profile EAPI
   !
   vrf MGMT
      no shutdown
```

## Caveats

| Topic | Status on EOS |
|-------|------------------------|
| Config | Profile valid; hybrid group only |
| Live wire | **PQC-safe** — TLS 1.3 + `X25519MLKEM768` |
| Client certs | Not required for eAPI in this lab (`admin` local auth) |

## Verification

### Configuration

```bash
docker exec -i arista-quantum-safe-ceos1-both Cli <<'EOF'
enable
show management security ssl profile EAPI detail
show management api http-commands
EOF
```

Expect `State: valid`, `X25519MLKEM768` in profile detail, `SSL Profile: EAPI`.

### Live PQC handshake

The lab runs OpenSSL 3.5 with PQC support inside the **test-runner** probe client (`arista-quantum-safe-test-runner`):

```bash
docker exec arista-quantum-safe-test-runner sh -c \
  'OPENSSL_CONF=/etc/probe/openssl-pqc.cnf \
   openssl s_client -connect 172.20.127.11:443 -tls1_3 \
   -CAfile /etc/probe/certs/radsec-ca.pem -brief </dev/null 2>&1' \
  | grep -E 'Protocol|Negotiated TLS1.3 group'
```

Expected:

```text
Protocol version: TLSv1.3
Negotiated TLS1.3 group: X25519MLKEM768
```

### JSON-RPC

```bash
docker exec arista-quantum-safe-test-runner sh -c \
  'OPENSSL_CONF=/etc/probe/openssl-pqc.cnf \
   curl -sk --tlsv1.3 --tls-max 1.3 -u admin: \
   https://172.20.127.11/command-api \
   -H "Content-Type: application/json" \
   -d "{\"jsonrpc\":\"2.0\",\"method\":\"runCmds\",\"params\":{\"version\":1,\"cmds\":[\"show version\"],\"format\":\"json\"},\"id\":1}"'
```

Automated: `make test-eapi` → eAPI HTTPS + JSON-RPC checks per node (IPv4 and IPv6).

See [eAPI tests](../tests/eapi.md).

<- [Services overview](index.md)
