# Syslog

Remote syslog uses **TLS 1.3** on port **6514** in VRF MGMT with ssl profile **`SYSLOG`**. The collector runs **syslog-ng** with OpenSSL 3.5.

| Item | Value |
|------|-------|
| Port | **6514** (TLS) |
| Profile | `SYSLOG` |
| KEX group | `X25519MLKEM768:ecdh_x25519:secp256r1` (hybrid + classical fallback) |
| Template | `configs/ceos/ceos*.cfg.in` → `lab/.gen/` |
| Peer config | `configs/syslog/syslog-ng.conf`, `docker/syslog/openssl-pqc.cnf` |
| Collector | syslog-ng on `172.20.127.53` / `2001:db8:127::53` |

See also [Certificates and TLS 1.3](../misc/certificates-and-tls13.md).

## Configuration

### SSL profile `SYSLOG` (EOS switch)

Complete profile from `configs/ceos/ceos1-both.cfg.in`:

```text
management security
   ssl profile SYSLOG
      tls versions 1.3
      key-establishment-group X25519MLKEM768:ecdh_x25519:secp256r1
      cipher v1.3 TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256
      certificate ceos1-both-client.pem key ceos1-both-client.key
      trust certificate radsec-ca.pem
```

Unlike eAPI/RadSec/gNMI profiles, **SYSLOG allows classical fallback groups** so delivery works while the EOS syslog TLS client may lack PQC-hybrid support on the wire.

### Service binding (EOS)

```text
logging vrf MGMT host 172.20.127.53 6514 protocol tls ssl-profile SYSLOG
logging vrf MGMT host 2001:db8:127::53 6514 protocol tls ssl-profile SYSLOG
```

Rendered templates use `${SYSLOG_SERVER_IPV4}` and `${SYSLOG_SERVER_IPV6}` placeholders.

### Peer — syslog-ng collector

Built from `docker/syslog/Dockerfile`. TLS listener in `configs/syslog/syslog-ng.conf`:

```text
source s_tls {
    network(
        ip("::")
        ip-protocol(6)
        port(6514)
        max-connections(32)
        transport("tls")
        tls(
            key-file("/etc/syslog-ng/certs/server.key")
            cert-file("/etc/syslog-ng/certs/server.pem")
            ca-file("/etc/syslog-ng/certs/ca.pem")
            peer-verify(optional-untrusted)
        )
    );
};
```

OpenSSL policy via `OPENSSL_CONF=/etc/syslog-ng/openssl-pqc.cnf` (`docker/syslog/openssl-pqc.cnf`):

```ini
Groups = X25519MLKEM768:secp256r1:X25519:ffdhe2048
CipherString = TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256
MinProtocol = TLSv1.3
MaxProtocol = TLSv1.3
```

Cleartext UDP/TCP **514 is disabled** — only TLS **6514** listens.

## Caveats

| Topic | Status on EOS |
|-------|------------------------|
| Config | Profile lists `X25519MLKEM768` first |
| Live wire (EOS → collector) | **Not PQC-safe** — typically negotiates **`x25519`** |
| Live wire (probe → collector) | **PQC-safe** when using PQC OpenSSL |

!!! warning "Known EOS gap — syslog client"
    The EOS syslog TLS **client** does not offer ML-KEM hybrid groups in ClientHello even when the ssl profile advertises them. The collector accepts classical `x25519`, so logs still flow.

    Tightening both sides to PQC-only would **break** remote syslog on current EOS builds.

!!! note "Connection limit"
    syslog-ng defaults to **`max-connections(10)`** in some builds; the lab template sets **32**. Each switch opens **persistent TLS sessions** to IPv4 and IPv6 collectors (two sessions per switch × three switches ≈ 6 slots). Leave headroom for probes and health checks.

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

### Live PQC handshake (collector-side)

From the **test-runner** probe client (matches `make test-syslog`):

```bash
docker exec arista-quantum-safe-test-runner sh -c \
  'OPENSSL_CONF=/etc/probe/openssl-pqc.cnf \
   openssl s_client -connect 172.20.127.53:6514 -servername syslog -tls1_3 \
   -groups X25519MLKEM768 \
   -CAfile /etc/probe/certs/ca.pem -brief </dev/null 2>&1' \
  | grep -E 'Protocol|Negotiated TLS1.3 group'
```

### Wire capture (EOS → collector)

EOS keeps long-lived sessions — bounce logging hosts to force a new handshake:

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

Expect group **29 (`x25519`)**, not **4588 (`X25519MLKEM768`)** — see [Syslog tests](../tests/syslog.md#result-summary) for recorded wire KEX.

Automated: `make test-syslog` (delivery + optional wire KEX capture with **WARN** when not PQC-safe).

See [Syslog tests](../tests/syslog.md).

## Other remarks

There are no other remarks.

<- [Services overview](index.md)
