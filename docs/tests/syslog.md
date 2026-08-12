# Syslog tests

`make test-syslog` runs `python -m lab.test_syslog`.

## What is checked

### Collector (syslog-ng)

| Check | Method |
|-------|--------|
| TLS listener :6514 | `netstat -ltn` — no cleartext :514 |
| OpenSSL PQC groups | `openssl list -tls-groups` |
| Health | Wait for container healthcheck **healthy** |

### Each cEOS node (ceos1-both, ceos2-pqc, ceos3-qkd)

| Check | Method |
|-------|--------|
| Logging config | Dual-stack TLS hosts only; no UDP/TCP cleartext |
| SYSLOG ssl profile | `show management security ssl profile SYSLOG detail` |
| Live delivery | `send log` with unique marker; verify in collector log |
| Cleartext guard | Ensure delivery did not fall back to plain TCP/UDP |

### Collector TLS probe

PQC-hybrid handshake from test client to syslog :6514 (IPv4 + IPv6).

## Pass criteria

- No cleartext logging destinations configured
- Messages arrive over TLS
- Collector-side probe negotiates `X25519MLKEM768`

## Caveat interaction

cEOS **syslog client** may use classical **`x25519`** on the wire (4.36.1F). `make test-syslog` validates **encrypted delivery** and collector PQC — it does **not** fail when the switch client skips PQC. Wire KEX warnings appear in `make test-pqc` when tcpdump capture succeeds.

## Manual reproduction

```bash
# Collector listeners
docker exec arista-quantum-safe-syslog netstat -ltn | grep 6514
docker inspect --format='{{.State.Health.Status}}' arista-quantum-safe-syslog

# Switch logging config
docker exec -i arista-quantum-safe-ceos2-pqc Cli <<'EOF'
enable
show logging
show management security ssl profile SYSLOG detail
EOF

# Send test message
docker exec -i arista-quantum-safe-ceos2-pqc Cli <<'EOF'
enable
send log level informational message quantum-safe-manual-probe
EOF

docker exec arista-quantum-safe-syslog tail -5 /var/log/syslog/eos.log
```

## OpenSSL probe

```bash
docker exec arista-quantum-safe-test-runner sh -c \
  'OPENSSL_CONF=/etc/probe/openssl-pqc.cnf \
   openssl s_client -connect 172.20.127.53:6514 -servername syslog -tls1_3 \
   -groups X25519MLKEM768 \
   -CAfile /etc/probe/certs/ca.pem -brief </dev/null 2>&1' \
  | grep -E 'TLSv1.3|X25519MLKEM768'
```

Configuration reference: [Syslog service](../services/syslog.md).

PQC suite overlap: [PQC tests — Syslog](pqc.md#syslog).
