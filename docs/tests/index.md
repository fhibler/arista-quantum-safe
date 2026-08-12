# Test suite overview

Live checks require a **deployed lab** (`make deploy`). Offline unit tests run via `make test` (pytest, no cEOS).

## `make test-lab`

Runs all sections in order:

| Step | Target | Module |
|------|--------|--------|
| 1 | `make test-radius` | `lab.test_lab` — radius section |
| 2 | `make test-kme` | `lab.test_kme` |
| 3 | `make test-pqc` | `lab.test_pqc_connections` |
| 4 | `make test-syslog` | `lab.test_syslog` |
| 5 | `make test-macsec` | `lab.test_macsec` |
| 6 | `make test-qkd` | `lab.test_qkd` (skips when QuaDRA extension absent — see [QKD service](../services/qkd-etsi014.md)) |
| 7 | `make test-hosts` | `lab.test_lab` — host routing matrix |

Use **`VERBOSE=1`** to echo every command and full output:

```bash
make test-pqc VERBOSE=1
```

## Check labels

| Label | Meaning |
|-------|---------|
| `[config]` | EOS `show` commands, listener presence, template contract |
| `[live]` | Real handshake, API call, AAA test, or traffic probe |
| `WARN` | Known platform gap — check passes with warning (not a failure) |

## Default management addresses

| Node | IPv4 | IPv6 |
|------|------|------|
| ceos1-both | 172.20.127.11 | 2001:db8:127::11 |
| ceos2-pqc | 172.20.127.12 | 2001:db8:127::12 |
| ceos3-qkd | 172.20.127.13 | 2001:db8:127::13 |
| radius | 172.20.127.50 | 2001:db8:127::50 |
| syslog | 172.20.127.53 | 2001:db8:127::53 |

Override subnet with `MGMT_SUBNET=… make test-lab`.

## Detailed test docs

- [PQC connectivity](pqc.md) — TLS 1.3 + hybrid KEX on all management services
- [RADIUS / RadSec](radius.md)
- [Syslog](syslog.md)
- [MACsec](macsec.md)

Configuration reference: [Services overview](../services/index.md).

## Offline tests

```bash
pip install -r requirements-dev.txt
make test
```

Validates topology contract, template rendering, helper parsers, and Docker image smoke tests without Containerlab deploy.

Docs site (MkDocs strict):

```bash
pip install -r docs/requirements.txt
mkdocs build --strict
```
