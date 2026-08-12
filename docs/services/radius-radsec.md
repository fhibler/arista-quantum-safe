# RADIUS / RadSec

FreeRADIUS provides **RadSec** (RADIUS over TLS 1.3) for AAA and **EAP-TLS** for 802.1X MACsec keying.

## Configuration

### EOS switch (RadSec client)

Ssl profile **`RADSEC`** — PQC-hybrid only:

```text
management security
   ssl profile RADSEC
      tls versions 1.3
      key-establishment-group X25519MLKEM768
      certificate ceos1-both-client.pem key ceos1-both-client.key
      trust certificate radsec-ca.pem
!
radius-server host 172.20.127.50 vrf MGMT tls ssl-profile RADSEC
!
aaa group server radius RADIUS
   server 172.20.127.50 tls vrf MGMT
```

| Item | Value |
|------|-------|
| Port | **2083** (RadSec) |
| Transport | TLS 1.3 mTLS |
| KEX | `X25519MLKEM768` only |

### FreeRADIUS (server)

Image: `docker/radius/Dockerfile` — FreeRADIUS 3.2.6 + OpenSSL 3.5.7.

Environment sets `OPENSSL_CONF=/etc/raddb/openssl-pqc.cnf`:

```text
Groups = X25519MLKEM768
MinProtocol = TLSv1.3
MaxProtocol = TLSv1.3
```

RadSec listener on **2083** with mutual certificate authentication.

### EAP-TLS (802.1X / MACsec)

The `mods-available/eap` module terminates EAP-TLS for dot1x supplicants. Supplicant ssl profile **`DOT1X`** also uses `X25519MLKEM768` for the inner TLS tunnel.

Policy `policy.d/macsec-dot1x` maps EAP session material for MKA key derivation.

## Caveats

| Topic | Status on cEOS 4.36.1F |
|-------|------------------------|
| RadSec config | PQC-hybrid only on switch and server |
| RadSec live wire | **PQC-safe** |
| EAP-TLS (dot1x) | **PQC-safe** — hybrid group in supplicant handshake |
| RADIUS shared secret | Lab uses TLS certs; RadSec port not classic UDP 1812 |

!!! note
    `test aaa` uses a lab-only `Auth-Type := Accept` policy for management AAA checks. Production deployments should use proper user credentials.

## Verification

### Server listener and groups

```bash
docker exec arista-quantum-safe-radius netstat -ltn | grep 2083
docker exec arista-quantum-safe-radius openssl list -tls-groups | grep X25519MLKEM768
```

### Switch config and AAA test

```bash
docker exec -i arista-quantum-safe-ceos1-both Cli <<'EOF'
enable
show management security ssl profile RADSEC detail
show running-config | section radius
test aaa group RADIUS server 172.20.127.50 tls port 2083 vrf MGMT
EOF
```

Expect `successfully authenticated`.

### OpenSSL RadSec handshake (from radius container to itself)

Simulates switch-side PQC client toward RadSec (use switch mgmt IP as connect target with switch client cert):

```bash
docker exec arista-quantum-safe-radius sh -c \
  'OPENSSL_CONF=/etc/raddb/openssl-pqc.cnf \
   openssl s_client -connect 172.20.127.50:2083 -tls1_3 \
   -CAfile /etc/raddb/certs/radsec/ca.pem \
   -cert /etc/raddb/certs/radsec/ceos1-both-client.pem \
   -key /etc/raddb/certs/radsec/ceos1-both-client.key \
   -brief </dev/null 2>&1' \
  | grep -E 'Protocol|Negotiated TLS1.3 group'
```

Automated: `make test-radius` and RadSec section of `make test-pqc`.

See [RADIUS tests](../tests/radius.md) and [PQC tests](../tests/pqc.md#radsec).

← [Services overview](index.md)
