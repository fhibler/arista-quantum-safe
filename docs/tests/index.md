# Test suite overview

Live checks require a **deployed lab** (`make deploy`). Offline unit tests run via `make test` (pytest, no deployed lab).

## `make test-lab`

Runs all sections in order (one pass per service, no duplication):

| Step | Target | Module |
|------|--------|--------|
| 1 | `make test-ssh` | `lab.test_ssh` |
| 2 | `make test-eapi` | `lab.test_eapi` |
| 3 | `make test-radsec` | `lab.test_radsec` |
| 4 | `make test-syslog` | `lab.test_syslog` |
| 5 | `make test-openconfig` | `lab.test_openconfig` |
| 6 | `make test-kme` | `lab.test_kme` |
| 7 | `make test-macsec-dot1x` | `lab.test_macsec_dot1x` |
| 8 | `make test-macsec-qkd` | `lab.test_macsec_qkd` (skips when QuaDRA extension absent — see [QKD service](../services/qkd-etsi014.md)) |
| 9 | `make test-hosts` | `lab.test_hosts` — host routing matrix |

On a **bare Linux host** without PQC-capable curl/OpenSSL on the host OS, use **`make test-lab-runner`** instead. It runs the same checks from the `test-runner` container on the lab mgmt network (Docker + deployed lab only).

PQC live probes (TLS handshakes, eAPI command-api, gNMI GET via gnmic, SSH) use the **`test-runner`** node (`arista-quantum-safe-test-runner`, mgmt `172.20.127.54`) by default. Override with `PROBE_CLIENT=radius` or `PROBE_CLIENT=host` when debugging.

Use **`VERBOSE=1`** to echo every command and full output:

```bash
make test-eapi VERBOSE=1
make test-radsec VERBOSE=1
make test-openconfig VERBOSE=1
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

## Suite summary line

Each `make test-*` target ends with a one-line summary that counts individual checks (`[config]`, `[live]`, `[live / test-runner]`, etc.):

```text
OpenConfig: ✓ — 87 passed, 12 warnings
HOSTS: ✓ — 12 passed
RadSec: ✓ — 42 passed
```

| Part | Meaning |
|------|---------|
| **Name** | Suite label (e.g. `OpenConfig`, `RadSec`, `HOSTS`) |
| **✓ / ✗** | Overall outcome — **✓** when no check failed; **✗** when the suite aborts |
| **passed** | Checks that completed successfully |
| **warnings** | Checks marked **WARN** (e.g. classical wire KEX) — still a pass |
| **failed** | Shown only when failed checks were recorded before abort |
| **skipped** | Checks marked **SKIP** (platform limitation — not a failure) |

Only non-zero buckets are shown. On failure the summary is printed to stderr, e.g. `OpenConfig FAILED: ✗ — <first error>`.

`make test-lab` prints each suite's summary in order, then `✓ All lab checks passed.` when every suite succeeds.

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

## Result summary

Expected **live** behavior on **EOS 4.36.2F** (3 switches, IPv4 + IPv6 unless noted).

| Service | Make target | TLS 1.3 compliant | KEX configured | KEX used (live) | PQC-safe |
|---------|-------------|---------------------|----------------|-----------------|----------|
| SSH | `test-ssh` | N/A (SSH, not TLS) | `mlkem768x25519-sha256` | `mlkem768x25519-sha256` | Yes |
| eAPI | `test-eapi` | Yes | `X25519MLKEM768` | `X25519MLKEM768` | Yes |
| gNMI | `test-openconfig` | Yes | `X25519MLKEM768` | `X25519MLKEM768` | Yes |
| gNOI (transport + RPC) | `test-openconfig` | Yes | `X25519MLKEM768` | `X25519MLKEM768` | Yes |
| gRIBI | `test-openconfig` | Yes | `X25519MLKEM768` | classical (`secp256r1`) | No |
| gNSI Certz | `test-openconfig` | Yes | `X25519MLKEM768` | `X25519MLKEM768` | Yes |
| gNPSI (TLS) | `test-openconfig` | Yes | `X25519MLKEM768` | classical (`secp256r1`) | No |
| gNPSI (Subscribe) | `test-openconfig` | Yes | `X25519MLKEM768` | classical (`secp256r1`) | No |
| RESTCONF | `test-openconfig` | Yes | `X25519MLKEM768` | `X25519MLKEM768` | Yes |
| RadSec | `test-radsec` | Yes | `X25519MLKEM768` | `X25519MLKEM768` | Yes |
| Syslog (EOS to collector) | `test-syslog` | Yes | `X25519MLKEM768` (+ classical fallback) | classical (`x25519`) | No |
| eos-sdk-rpc (IPv4) | `test-openconfig` | Yes | `X25519MLKEM768` | classical (`secp256r1`) | No |
| eos-sdk-rpc (IPv6) | `test-openconfig` | SKIP | `X25519MLKEM768` | — (no listener) | — |
| Syslog collector probe | `test-syslog` | Yes | `X25519MLKEM768` (+ classical fallback) | `X25519MLKEM768` | Yes |

**Columns**

| Column | Meaning |
|--------|---------|
| **TLS 1.3 compliant** | Live session uses TLS 1.3 (or SSH for port 22). **Yes** = encrypted with the expected protocol version; **No** = handshake fails or falls back. |
| **KEX configured** | Key-establishment group(s) in EOS `ssl profile` or `management ssh` config (what the switch is configured to offer). |
| **KEX used (live)** | Group negotiated on the wire during the listed make target. |
| **PQC-safe** | **Yes** when the live KEX is the lab hybrid (`X25519MLKEM768` or `mlkem768x25519-sha256`); **No** when classical KEX is used or PQC negotiation fails. **`WARN`** in suite output means the check still passes — it is not a PQC-safe value. |
| **SKIP** | Check not run — known platform/config limitation (not a failure). |

**Notes**

- **Syslog (EOS to collector):** TLS 1.3 delivery succeeds, but the EOS syslog TLS client typically negotiates classical **`x25519`** despite the profile listing hybrid first — not PQC-safe, still TLS 1.3 compliant. `make test-syslog` reports **WARN** when tcpdump capture confirms classical wire KEX.
- **eos-sdk-rpc (IPv4):** PQC-only probe gets **EOF** on port **9543**; fallback **`-groups secp256r1`** completes TLS 1.3 with classical KEX — not PQC-safe, TLS 1.3 compliant.
- **gRIBI (IPv4/IPv6):** PQC-only OpenSSL mTLS on port **9340** gets **handshake failure**; explicit **`-groups secp256r1`** completes TLS 1.3 with classical KEX despite strict **`GRIBI`** profile — `make test-openconfig` reports **WARN** (same pattern as eos-sdk-rpc).
- **gNPSI (IPv4/IPv6):** Same wire gap as gRIBI on port **6031** — PQC-only OpenSSL mTLS fails; explicit **`-groups secp256r1`** completes TLS 1.3 with classical KEX — `make test-openconfig` reports **WARN** on mTLS, reflection, and Subscribe.
- **gNPSI Subscribe:** `grpcurl` `gnpsi.gNPSI/Subscribe` receives sFlow datagrams on **IPv4 and IPv6** when sampled interfaces carry traffic (typical on a deployed lab). **SKIP** only when no datagram arrives within the 8 s probe window — run `make test-hosts` and retry if needed.
- **eos-sdk-rpc (IPv6):** **SKIP** in `make test-openconfig` (IPv4-only service binding on Management0).

## Detailed test docs

- [eAPI](eapi.md) — HTTPS + JSON-RPC PQC (`make test-eapi`)
- [SSH](ssh.md) — management SSH PQC KEX (`make test-ssh`)
- [RadSec](radsec.md) — reachability, AAA, collector TLS (`make test-radsec`)
- [OpenConfig connectivity](openconfig.md) — gNMI, gNOI, gRIBI, gNSI, gNPSI, RESTCONF, eos-sdk-rpc (`make test-openconfig`)
- [Syslog](syslog.md) — TLS delivery + collector PQC (`make test-syslog`)
- [KME (ETSI QKD 014)](kme.md) — SAE status + enc/dec round-trip (`make test-kme`)
- [MACsec 802.1X](macsec-dot1x.md)
- [MACsec QuaDRA QKD](macsec-qkd.md)
- [Host routing](hosts.md) — data-plane ping matrix (`make test-hosts`)

Configuration reference: [Services overview](../services/index.md).

## Offline tests

```bash
pip install -r requirements-dev.txt
make test
```

Validates topology contract, template rendering, helper parsers, and Docker image smoke tests without Containerlab deploy.

## Documentation site (local build)

Build this site locally with:

```bash
pip install -r docs/requirements.txt
mkdocs build --strict
```

Published docs are deployed automatically via GitHub Actions on push to `main`.
