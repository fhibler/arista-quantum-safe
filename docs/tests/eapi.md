# eAPI tests

`make test-eapi` runs `python -m lab.test_eapi` against all three EOS nodes (**ceos1-both**, **ceos2-pqc**, **ceos3-qkd**) on **IPv4 and IPv6**.

**Policy:** TLS 1.3 with PQC-hybrid group **`X25519MLKEM768`** — no classical fallback on the `EAPI` ssl profile.

OpenSSL and curl probes run **inside `arista-quantum-safe-test-runner`** (default `PROBE_CLIENT`) with `OPENSSL_CONF=/etc/probe/openssl-pqc.cnf`. Override with `PROBE_CLIENT=radius` or `PROBE_CLIENT=host` when debugging.

## What is checked

| Check | Type | Method |
|-------|------|--------|
| ssl profile `EAPI` | `[config]` | `show management security ssl profile EAPI detail` |
| http-commands binding | `[config]` | `show management api http-commands` |
| HTTPS :443 handshake | `[live / test-runner]` | `openssl s_client` with PQC groups |
| command-api JSON-RPC | `[live / test-runner]` | PQC `curl` `runCmds` |

## Manual reproduction

**Live HTTPS** (test-runner by default):

```bash
docker exec arista-quantum-safe-test-runner sh -c \
  'OPENSSL_CONF=/etc/probe/openssl-pqc.cnf \
   openssl s_client -connect 172.20.127.11:443 -tls1_3 \
   -CAfile /etc/probe/certs/radsec-ca.pem -brief </dev/null 2>&1'
```

**Live eAPI command-api:**

```bash
docker exec arista-quantum-safe-test-runner sh -c \
  'OPENSSL_CONF=/etc/probe/openssl-pqc.cnf \
   curl -sk --tlsv1.3 --tls-max 1.3 -u admin: \
   https://172.20.127.11/command-api \
   -H "Content-Type: application/json" \
   -d "{\"jsonrpc\":\"2.0\",\"method\":\"runCmds\",\"params\":{\"version\":1,\"cmds\":[\"show version\"],\"format\":\"json\"},\"id\":1}"'
```

Set `PROBE_CLIENT=host` to use host curl (devcontainer only) or `PROBE_CLIENT=radius` to fall back to the radius container.

Configuration reference: [eAPI service](../services/eapi.md).

See [Test suite overview](index.md#result-summary) for expected live KEX on **EOS 4.36.2F**.
