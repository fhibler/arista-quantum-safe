# RADIUS / RadSec

FreeRADIUS provides **RadSec** (RADIUS over TLS 1.3) for AAA and **EAP-TLS** for 802.1X MACsec keying.

| Item | Value |
|------|-------|
| Port | **2083** (RadSec) |
| Profile | `RADSEC` (switch); `DOT1X` (EAP-TLS supplicant) |
| KEX | `X25519MLKEM768` only (strict profiles) |
| Template | `configs/ceos/ceos*.cfg.in` → `lab/.gen/` |
| Peer config | `configs/radius/raddb/`, `docker/radius/openssl-pqc.cnf` |

See also [Certificates and TLS 1.3](../misc/certificates-and-tls13.md) and [MACsec](macsec.md).

## Configuration

### SSL profile `RADSEC` (EOS switch)

Complete profile from `configs/ceos/ceos1-both.cfg.in`:

```text
management security
   ssl profile RADSEC
      tls versions 1.3
      key-establishment-group X25519MLKEM768
      cipher v1.3 TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256
      certificate ceos1-both-client.pem key ceos1-both-client.key
      trust certificate radsec-ca.pem
```

### Service binding (EOS)

```text
radius-server host 172.20.127.50 vrf MGMT tls ssl-profile RADSEC
!
aaa group server radius RADIUS
   server 172.20.127.50 tls vrf MGMT
```

Rendered templates use `${RADIUS_SERVER_IP}` for the server address.

### SSL profile `DOT1X` (EAP-TLS supplicant)

On **ceos2-pqc** only (`configs/ceos/ceos2-pqc.cfg.in`):

```text
management security
   ssl profile DOT1X
      tls versions 1.3
      key-establishment-group X25519MLKEM768
      cipher v1.3 TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256
      certificate ceos2-pqc-client.pem key ceos2-pqc-client.key
      trust certificate radsec-ca.pem
!
dot1x
   supplicant profile macsec-sp
      identity ceos2-pqc
      eap-method tls
      ssl profile DOT1X
```

### Peer — FreeRADIUS (RadSec server)

Image: `docker/radius/Dockerfile` — FreeRADIUS 3.2.6 + OpenSSL 3.5.7.

RadSec listener in `configs/radius/raddb/sites-available/tls`:

```text
listen {
	ipaddr = *
	port = 2083
	type = auth+acct
	proto = tcp
	virtual_server = default
	clients = radsec

	tls {
		private_key_file = /etc/raddb/certs/radsec/server.pem
		certificate_file = /etc/raddb/certs/radsec/server.pem
		ca_file = /etc/raddb/certs/radsec/ca.pem
		tls_min_version = "1.3"
		tls_max_version = "1.3"
		require_client_cert = yes
		ecdh_curve = ""
	}
}
```

OpenSSL policy via `OPENSSL_CONF=/etc/raddb/openssl-pqc.cnf`:

```ini
Groups = X25519MLKEM768
CipherString = TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256
MinProtocol = TLSv1.3
MaxProtocol = TLSv1.3
```

EAP-TLS for 802.1X is terminated in `mods-available/eap`. Policy `policy.d/macsec-dot1x` maps EAP session material for MKA key derivation.

## Caveats

| Topic | Status on EOS |
|-------|------------------------|
| Config | PQC-hybrid only on switch and server |
| Live wire (RadSec) | **PQC-safe** |
| Live wire (EAP-TLS) | **PQC-safe** — hybrid group in supplicant handshake |
| RADIUS shared secret | Lab uses TLS certs; RadSec port not classic UDP 1812 |

!!! note "Lab AAA policy"
    `test aaa` uses a lab-only `Auth-Type := Accept` policy for management AAA checks. Production deployments should use proper user credentials.

## Verification

### Configuration

```bash
docker exec arista-quantum-safe-radius netstat -ltn | grep 2083
docker exec arista-quantum-safe-radius openssl list -tls-groups | grep X25519MLKEM768
```

```bash
docker exec -i arista-quantum-safe-ceos1-both Cli <<'EOF'
enable
show management security ssl profile RADSEC detail
show running-config | section radius
test aaa group RADIUS server 172.20.127.50 tls port 2083 vrf MGMT
EOF
```

Expect `successfully authenticated`.

### Live PQC handshake

Simulates switch-side PQC client toward RadSec (switch client cert mounted in the test-runner probe client):

```bash
docker exec arista-quantum-safe-test-runner sh -c \
  'OPENSSL_CONF=/etc/probe/openssl-pqc.cnf \
   openssl s_client -connect 172.20.127.50:2083 -tls1_3 \
   -CAfile /etc/probe/certs/radsec-ca.pem \
   -cert /etc/probe/certs/ceos1-both-client.pem \
   -key /etc/probe/certs/ceos1-both-client.key \
   -brief </dev/null 2>&1' \
  | grep -E 'Protocol|Negotiated TLS1.3 group'
```

Automated: `make test-radsec` (reachability, AAA, collector TLS PQC).

See [RadSec tests](../tests/radsec.md).

## Other remarks

There are no other remarks.

<- [Services overview](index.md)
