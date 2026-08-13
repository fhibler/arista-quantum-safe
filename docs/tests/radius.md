# RADIUS tests

`make test-radius` runs the **radius** section of `lab.test_lab`.

## What is checked

### FreeRADIUS container

| Check | Method |
|-------|--------|
| RadSec listener on :2083 | `docker exec … netstat -ltn` |
| OpenSSL offers `X25519MLKEM768` | `openssl list -tls-groups` |
| Radius config contract | `check_radius_config()` |

### Each EOS switch (ceos1-both, ceos2-pqc, ceos3-qkd)

| Check | Method |
|-------|--------|
| MGMT reachability | `ping vrf MGMT <radius-ip> repeat 3` (IPv4 + IPv6) |
| RadSec profile + config | `check_radsec_config()` — ssl profile RADSEC, radius transport |
| RadSec AAA | `test aaa group RADIUS server … tls port 2083 vrf MGMT` (IPv4 + IPv6) |

## Pass criteria

- 0% packet loss to radius on both address families
- RadSec ssl profile **valid** with PQC-hybrid group
- `test aaa` returns **successfully authenticated**

## Manual reproduction

```bash
# Radius listener
docker exec arista-quantum-safe-radius netstat -ltn | grep 2083

# Switch -> radius ping
docker exec -i arista-quantum-safe-ceos1-both Cli <<'EOF'
enable
ping vrf MGMT 172.20.127.50 repeat 3
EOF

# RadSec AAA
docker exec -i arista-quantum-safe-ceos1-both Cli <<'EOF'
enable
test aaa group RADIUS server 172.20.127.50 tls port 2083 vrf MGMT
EOF
```

## OpenSSL handshake check

Verify TLS 1.3 + `X25519MLKEM768` on RadSec (switch client credentials):

```bash
docker exec arista-quantum-safe-test-runner sh -c \
  'OPENSSL_CONF=/etc/probe/openssl-pqc.cnf \
   openssl s_client -connect 172.20.127.50:2083 -tls1_3 \
   -CAfile /etc/probe/certs/radsec-ca.pem \
   -cert /etc/probe/certs/ceos1-both-client.pem \
   -key /etc/probe/certs/ceos1-both-client.key \
   -brief </dev/null 2>&1' \
  | grep X25519MLKEM768
```

Configuration reference: [RADIUS / RadSec service](../services/radius-radsec.md).

Also covered by `make test-pqc` (RadSec section per node).
