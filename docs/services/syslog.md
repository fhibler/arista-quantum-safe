# Syslog

Remote syslog uses **TLS 1.3** on port **6514** in VRF MGMT with ssl profile **`SYSLOG`**. The collector runs **syslog-ng** with OpenSSL 3.5.

## Configuration

### EOS (switch)

```text
management security
   ssl profile SYSLOG
      tls versions 1.3
      key-establishment-group X25519MLKEM768:ecdh_x25519:secp256r1
      ...
!
logging vrf MGMT host 172.20.127.53 6514 protocol tls ssl-profile SYSLOG
logging vrf MGMT host 2001:db8:127::53 6514 protocol tls ssl-profile SYSLOG
```

Unlike eAPI/RadSec/gNMI profiles, **SYSLOG allows classical fallback groups** in the template so delivery works while the EOS syslog TLS client lacks PQC-hybrid support.

### Collector (syslog-ng)

Built from `docker/syslog/Dockerfile` with `docker/syslog/openssl-pqc.cnf`:

```text
Groups = X25519MLKEM768:secp256r1:X25519:ffdhe2048
```

Cleartext UDP/TCP **514 is disabled** — only TLS **6514** listens.

## Caveats

!!! warning "Known cEOS 4.36.1F gap — syslog client"
    | Topic | Status |
    |-------|--------|
    | Config | Profile lists `X25519MLKEM768` first |
    | Live wire (cEOS -> syslog-ng) | **Not PQC-safe** — typically negotiates **`x25519`** |
    | Collector probe (client -> syslog-ng) | **PQC-safe** when using PQC OpenSSL |

    The EOS syslog TLS **client** does not offer ML-KEM hybrid groups in ClientHello even when the ssl profile advertises them. The collector accepts classical `x25519`, so logs still flow.

    Tightening both sides to PQC-only would **break** remote syslog on 4.36.1F.

### Connection limit

syslog-ng defaults to **`max-connections(10)`**. Each switch opens **persistent TLS sessions** to IPv4 and IPv6 collectors (two sessions per switch × three switches ≈ 10 slots). Leave headroom for probes and health checks.

## Verification

### Configuration

```bash
docker exec -i arista-quantum-safe-ceos2-pqc Cli <<'EOF'
enable
show logging
show management security ssl profile SYSLOG detail
EOF
```

```bash
docker exec arista-quantum-safe-syslog netstat -ltn | grep 6514
docker exec arista-quantum-safe-syslog openssl list -tls-groups | grep X25519MLKEM768
```

### Collector-side PQC handshake

```bash
docker exec arista-quantum-safe-radius sh -c \
  'OPENSSL_CONF=/etc/raddb/openssl-pqc.cnf \
   openssl s_client -connect 172.20.127.53:6514 -tls1_3 \
   -CAfile /etc/raddb/certs/radsec/ca.pem -brief </dev/null 2>&1' \
  | grep -E 'Protocol|Negotiated TLS1.3 group'
```

### Wire capture (cEOS -> collector)

cEOS keeps long-lived sessions — bounce logging hosts to force a new handshake:

```bash
# Terminal A — on Docker host (mgmt bridge)
tcpdump -i mgmt-bridge -n -s 0 -w /tmp/syslog-tls.pcap 'tcp port 6514'

# Terminal B — bounce logging on a switch
docker exec -i arista-quantum-safe-ceos2-pqc Cli <<'EOF'
enable
configure
no logging vrf MGMT host 172.20.127.53 6514 protocol tls ssl-profile SYSLOG
no logging vrf MGMT host 2001:db8:127::53 6514 protocol tls ssl-profile SYSLOG
logging vrf MGMT host 172.20.127.53 6514 protocol tls ssl-profile SYSLOG
logging vrf MGMT host 2001:db8:127::53 6514 protocol tls ssl-profile SYSLOG
end
EOF
```

Decode with tshark (install in syslog container if needed):

```bash
docker exec arista-quantum-safe-syslog tshark -r /tmp/syslog-tls.pcap \
  -Y 'tls.handshake.type == 1' \
  -T fields -e tls.handshake.extensions_key_share_group \
  2>/dev/null | head
```

On 4.36.1F expect group **29 (`x25519`)**, not **4588 (`X25519MLKEM768`)**.

Automated: `make test-pqc` (delivery + optional wire KEX capture) and `make test-syslog`.

See [Syslog tests](../tests/syslog.md).

<- [Services overview](index.md)
