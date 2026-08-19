# Syslog tests

`make test-syslog` runs `python -m lab.test_syslog`.

**Policy:** Encrypted delivery over TLS 1.3. The collector offers **`X25519MLKEM768`**; the EOS syslog client may still negotiate classical **`x25519`** on the wire (see [Syslog caveats](../services/syslog.md#caveats)).

## What is checked

### Collector (syslog-ng)

| Check | Type | Method |
|-------|------|--------|
| TLS listener :6514 | `[config]` | `netstat -ltn` — no cleartext :514 |
| OpenSSL PQC groups | `[config]` | `openssl list -tls-groups` |
| Health | `[config]` | Wait for container healthcheck **healthy** |

### Each EOS node (ceos1-both, ceos2-pqc, ceos3-qkd)

| Check | Type | Method |
|-------|------|--------|
| Logging config | `[config]` | Dual-stack TLS hosts only; no UDP/TCP cleartext |
| SYSLOG ssl profile | `[config]` | `show management security ssl profile SYSLOG detail` |
| Live delivery | `[live]` | `send log` with unique marker; verify in collector log |
| Cleartext guard | `[live]` | Ensure delivery did not fall back to plain TCP/UDP |

### Collector TLS probe

| Check | Type | Method |
|-------|------|--------|
| Collector PQC handshake | `[live / test-runner]` | PQC-hybrid `openssl s_client` to syslog :6514 (IPv4 + IPv6) |
| EOS → collector wire KEX | `[live]` | Optional tcpdump/tshark capture — **WARN** when classical |

## Pass criteria

- No cleartext logging destinations configured
- Messages arrive over TLS
- Collector-side probe negotiates `X25519MLKEM768`

## Expected SKIP / WARN

EOS **syslog client** may use classical **`x25519`** on the wire — **not PQC-safe**, TLS 1.3 compliant. `make test-syslog` validates **encrypted delivery**, collector PQC, and reports **WARN** when tcpdump capture confirms classical wire KEX.

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

# Collector PQC probe
docker exec arista-quantum-safe-test-runner sh -c \
  'OPENSSL_CONF=/etc/probe/openssl-pqc.cnf \
   openssl s_client -connect 172.20.127.53:6514 -servername syslog -tls1_3 \
   -groups X25519MLKEM768 \
   -CAfile /etc/probe/certs/ca.pem -brief </dev/null 2>&1' \
  | grep -E 'TLSv1.3|X25519MLKEM768'
```

## Result summary

Recorded on **EOS 4.36.2F** (3 switches, IPv4 + IPv6):

| Check | Expected | Outcome |
|-------|----------|---------|
| No cleartext logging hosts | TLS-only `logging host … 6514` | PASS |
| SYSLOG ssl profile | `X25519MLKEM768` listed first (+ classical fallback) | PASS |
| Live message delivery | Needle in collector log over TLS | PASS |
| Collector PQC probe | `X25519MLKEM768` from test-runner | PASS |
| EOS to collector wire KEX | Often **`x25519`** (not hybrid) | PASS + **WARN** in `make test-syslog` when captured |

See also [Test suite overview — Result summary](index.md#result-summary) for the full management-plane matrix.

Configuration reference: [Syslog service](../services/syslog.md).

<- [Test suite overview](index.md)
