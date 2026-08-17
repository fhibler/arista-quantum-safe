# Test suite overview

Live checks require a **deployed lab** (`make deploy`). Offline unit tests run via `make test` (pytest, no deployed lab).

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

On a **bare Linux host** without PQC-capable curl/OpenSSL on the host OS, use **`make test-lab-runner`** instead. It runs the same checks from the `test-runner` container on the lab mgmt network (Docker + deployed lab only).

PQC live probes (TLS handshakes, eAPI command-api, gNMI GET via gnmic, SSH) use the **`test-runner`** node (`arista-quantum-safe-test-runner`, mgmt `172.20.127.54`) by default. Override with `PROBE_CLIENT=radius` or `PROBE_CLIENT=host` when debugging.

Use **`VERBOSE=1`** to echo every command and full output:

```bash
make test-pqc VERBOSE=1
```

## Check labels

| Label | Meaning |
|-------|---------|
| `[config]` | EOS `show` commands, listener presence, template contract |
| `[live]` | Real handshake, API call, AAA test, or traffic probe (non-probe-client checks) |
| `[live / test-runner]` | Live probe executed from the test-runner container (default `PROBE_CLIENT`) |
| `[live / radius]` | Live probe executed from the radius container (`PROBE_CLIENT=radius`) |
| `[live / host]` | Live probe executed on the host (`PROBE_CLIENT=host`) |
| `WARN` | **Not PQC-safe** (often still TLS 1.3 compliant); check passes (not a failure) |
| `SKIP` | Known platform/config limitation — check not run (not a failure) |

## Default management addresses

| Node | IPv4 | IPv6 |
|------|------|------|
| ceos1-both | 172.20.127.11 | 2001:db8:127::11 |
| ceos2-pqc | 172.20.127.12 | 2001:db8:127::12 |
| ceos3-qkd | 172.20.127.13 | 2001:db8:127::13 |
| radius | 172.20.127.50 | 2001:db8:127::50 |
| syslog | 172.20.127.53 | 2001:db8:127::53 |
| test-runner | 172.20.127.54 | 2001:db8:127::54 |

Override subnet with `MGMT_SUBNET=… make test-lab`.

## Recorded test results

Result tables in the detailed test pages reflect live runs against the lab default image **EOS 4.36.2F** (`CEOS_IMAGE=ceos:4.36.2F`; see [Setup](../setup.md)).

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
