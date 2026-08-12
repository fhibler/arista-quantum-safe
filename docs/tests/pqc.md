# PQC connectivity tests

`make test-pqc` runs `python -m lab.test_pqc_connections` against all three cEOS nodes (**ceos1-both**, **ceos2-pqc**, **ceos3-qkd**) on **IPv4 and IPv6**.

**Policy:** TLS 1.3 with PQC-hybrid group **`X25519MLKEM768`** — no classical fallback on strict profiles. SSH uses **`mlkem768x25519-sha256`**.

OpenSSL probes run **inside `arista-quantum-safe-test-runner`** (default `PROBE_CLIENT`) with `OPENSSL_CONF=/etc/probe/openssl-pqc.cnf`. Override with `PROBE_CLIENT=radius` or `PROBE_CLIENT=host` when debugging.

## What is checked

### Radius + syslog collectors (once)

| Check | Type | Method |
|-------|------|--------|
| RadSec listener :2083 | `[config]` | `netstat -ltn` in radius container |
| OpenSSL groups include hybrid | `[config]` | `openssl list -tls-groups` |
| Syslog TLS :6514 only | `[config]` | No UDP/TCP 514; TLS listener present |
| Collector PQC handshake | `[live]` | `openssl s_client` to syslog :6514 |

### Per switch (×3 nodes, ×2 address families)

| Service | Config checks | Live checks |
|---------|---------------|-------------|
| eAPI | ssl profile EAPI, http-commands binding | HTTPS :443 + command-api `runCmds` |
| gNMI | ssl profile GNMI, mTLS trust | TLS + mTLS :6030 |
| RESTCONF | ssl profile RESTCONF | HTTPS :6020 |
| eos-sdk-rpc | ssl profile GNMI, service enabled | mTLS :9543 (**WARN** on gap) |
| SSH | `management ssh` KEX, VRF MGMT | SSH from **test-runner** probe client |
| Syslog | logging hosts, SYSLOG profile | Message delivery + optional wire KEX |
| RadSec | RADSEC profile, radius config | `test aaa … tls port 2083` |

---

## SSH

**Live:** SSH from **`test-runner`** (`arista-quantum-safe-test-runner`) to switch mgmt IP with `-o KexAlgorithms=mlkem768x25519-sha256`.

**Pass criteria:** Exit 0, output contains `kex: algorithm: mlkem768x25519-sha256` and hostname JSON.

Manual equivalent:

```bash
docker exec arista-quantum-safe-test-runner sh -c \
  'ssh -vvv \
     -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
     -o PubkeyAuthentication=no -o PreferredAuthentications=keyboard-interactive \
     -o KexAlgorithms=mlkem768x25519-sha256 \
     admin@172.20.127.11 "show hostname | json" 2>&1' \
  | grep "kex: algorithm"
```

Set `PROBE_CLIENT=host` to use the host SSH client (devcontainer with OpenSSH 10+).

---

## eAPI

**Config:** `show management security ssl profile EAPI detail` -> valid + `X25519MLKEM768`.

**Live HTTPS** (test-runner by default):

```bash
docker exec arista-quantum-safe-test-runner sh -c \
  'OPENSSL_CONF=/etc/probe/openssl-pqc.cnf \
   openssl s_client -connect 172.20.127.11:443 -tls1_3 \
   -CAfile /etc/probe/certs/radsec-ca.pem -brief </dev/null 2>&1'
```

**Live eAPI command-api:** PQC `curl` from the **test-runner** container (default probe client):

```bash
docker exec arista-quantum-safe-test-runner sh -c \
  'OPENSSL_CONF=/etc/probe/openssl-pqc.cnf \
   curl -sk --tlsv1.3 --tls-max 1.3 -u admin: \
   https://172.20.127.11/command-api \
   -H "Content-Type: application/json" \
   -d "{\"jsonrpc\":\"2.0\",\"method\":\"runCmds\",\"params\":{\"version\":1,\"cmds\":[\"show version\"],\"format\":\"json\"},\"id\":1}"'
```

Set `PROBE_CLIENT=host` to use host curl (devcontainer only) or `PROBE_CLIENT=radius` to fall back to the radius container.

---

## gNMI / RESTCONF / eos-sdk-rpc

**gNMI TLS** (:6030), **mTLS** (client cert `ceos*-client.pem`), and **GET** (gnmic, same client cert):

```bash
docker exec arista-quantum-safe-test-runner sh -c \
  'OPENSSL_CONF=/etc/probe/openssl-pqc.cnf \
   openssl s_client -connect 172.20.127.11:6030 -tls1_3 \
   -CAfile /etc/probe/certs/radsec-ca.pem \
   -cert /etc/probe/certs/ceos1-both-client.pem \
   -key /etc/probe/certs/ceos1-both-client.key \
   -brief </dev/null 2>&1' \
  | grep -E 'TLSv1.3|X25519MLKEM768'

docker exec arista-quantum-safe-test-runner gnmic -a 172.20.127.11:6030 \
  --tls-ca /etc/probe/certs/radsec-ca.pem \
  --tls-cert /etc/probe/certs/ceos1-both-client.pem \
  --tls-key /etc/probe/certs/ceos1-both-client.key \
  --tls-version 1.3 --tls-min-version 1.3 --tls-max-version 1.3 \
  get --path '/system/config/hostname' --format json
```

**RESTCONF** (:6020): same pattern without client cert.

**eos-sdk-rpc** (:9543): same mTLS command. Test **WARN**s if PQC group not negotiated (known 4.36.1F gap).

---

## RadSec

**Config:** RADSEC profile valid; `tls ssl-profile RADSEC` in radius section.

**Live:** EOS CLI:

```text
test aaa group RADIUS server 172.20.127.50 tls port 2083 vrf MGMT
```

Expect `successfully authenticated`.

OpenSSL equivalent (from test-runner, switch client cert):

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

---

## Syslog

**Config:** Dual-stack TLS logging hosts; SYSLOG profile valid; no cleartext `logging host`.

**Live delivery:** `send log` with unique needle; verify message in collector without cleartext fallback.

**Wire KEX (optional):** tcpdump on syslog collector `eth0` during logging-host bounce — if captured, **WARN** when group ≠ PQC hybrid (4.36.1F client gap).

Collector probe (always PQC from test-runner):

```bash
docker exec arista-quantum-safe-test-runner sh -c \
  'OPENSSL_CONF=/etc/probe/openssl-pqc.cnf \
   openssl s_client -connect 172.20.127.53:6514 -servername syslog -tls1_3 \
   -groups X25519MLKEM768 \
   -CAfile /etc/probe/certs/ca.pem -brief </dev/null 2>&1'
```

---

## Result summary

| Service | Expected live KEX (4.36.1F) | Test outcome |
|---------|----------------------------|--------------|
| SSH | `mlkem768x25519-sha256` | PASS |
| eAPI | `X25519MLKEM768` | PASS |
| gNMI / RESTCONF | `X25519MLKEM768` | PASS |
| RadSec | `X25519MLKEM768` | PASS |
| Syslog (cEOS client) | Often `x25519` | PASS + **WARN** |
| eos-sdk-rpc | Often classical / EOF | PASS + **WARN** |

See service pages for configuration context: [Services overview](../services/index.md), [SSH](../services/ssh.md), [eAPI](../services/eapi.md), [OpenConfig](../services/openconfig.md), [Syslog](../services/syslog.md), [RadSec](../services/radius-radsec.md).
