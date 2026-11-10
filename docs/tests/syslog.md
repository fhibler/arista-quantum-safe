# Syslog tests

`make test-syslog` runs `python -m lab.test_syslog`.

**Wait times:** collector health polls for up to **90 s**. Each switch/address-family delivery check polls for up to **45 s** (plus 0.5 s capture setup), followed by wire verification taking **7.5 s** on the first capture or up to **19 s** in capture/reconnect/retry waits across two attempts. Six sequential wire checks therefore add about **45 s** normally or at most **114 s** of intentional waits. Command/decode time is extra; health/delivery polls can overrun by one 2 s interval. The cleartext guard runs concurrently for up to 30 s and stops when delivery completes. See [Wait times](index.md#wait-times).

**Policy:** Encrypted delivery over TLS 1.3. EOS **4.37.0F** negotiates **`X25519MLKEM768`** to the collector on all three switches over IPv4 and IPv6; classical fallback remains configured (see [Syslog caveats](../services/syslog.md#caveats)).

## What is checked

### Collector (syslog-ng)

| Check | Type | Method |
|-------|------|--------|
| TLS listener :6514 | `[config]` | `netstat -ltn` - no cleartext :514 |
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
| EOS → collector wire KEX | `[live]` | tcpdump/tshark capture of **ServerHello selected group** - **WARN** when classical |

## Pass criteria

- No cleartext logging destinations configured
- Messages arrive over TLS
- Collector-side probe negotiates `X25519MLKEM768`
- Captured EOS-to-collector ServerHello selects `X25519MLKEM768` on 4.37.0F; delivery alone does not establish PQC safety

## Expected SKIP / WARN

The recorded **4.37.0F** run has **15 passed**, with no warnings. Classical KEX produces **WARN**; an unavailable or incomplete capture leaves wire KEX unverified. A collector-only probe cannot prove the switch’s negotiated group.

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

Recorded on **EOS 4.37.0F** (3 switches, IPv4 + IPv6):

| Check | Expected | Outcome |
|-------|----------|---------|
| No cleartext logging hosts | TLS-only `logging host … 6514` | PASS |
| SYSLOG ssl profile | `X25519MLKEM768` listed first (+ classical fallback) | PASS |
| Live message delivery | Unique marker from this run in collector log over TLS | PASS |
| Collector PQC probe | `X25519MLKEM768` from test-runner | PASS |
| EOS to collector wire KEX | ServerHello selects **4588 (`X25519MLKEM768`)**, all six connections | PASS |

See also [Test suite overview - Result summary](index.md#result-summary) for the full management-plane matrix.

Configuration reference: [Syslog service](../services/syslog.md).

<- [Test suite overview](index.md)
