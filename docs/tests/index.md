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
| 8 | `make test-macsec-qkd` | `lab.test_macsec_qkd` (skips when QuaDRA extension absent - see [QKD service](../services/qkd-etsi014.md)) |
| 9 | `make test-hosts` | `lab.test_hosts` - host routing matrix |

Optional extended wait: **`make test-macsec-dot1x-reauth`** (~75 s) - see [MACsec 802.1X](macsec-dot1x.md).

On a **bare Linux host** without PQC-capable curl/OpenSSL on the host OS, use **`make test-lab-runner`** instead. It runs the same checks from the `test-runner` container on the lab mgmt network (Docker + deployed lab only).

PQC live probes (TLS handshakes, eAPI command-api, gNMI GET via gnmic, SSH) use the **`test-runner`** node (`arista-quantum-safe-test-runner`, mgmt `172.20.127.54`) by default. Override with `PROBE_CLIENT=radius` or `PROBE_CLIENT=host` when debugging.

Use **`VERBOSE=1`** to echo every command and full output:

```bash
make test-ssh VERBOSE=1
make test-eapi VERBOSE=1
make test-openconfig VERBOSE=1
```

Each test page follows the same chapter order: **What is checked** (`Check | Type | Method`, using the labels below) → **Pass criteria** → **Expected SKIP / WARN** (when the suite can warn or skip) → **Manual reproduction** → footer (**Configuration reference** to the matching service page, then the [Result summary](#result-summary) link when the check records live KEX). Multi-protocol pages ([OpenConfig](openconfig.md)) keep a grouped check table and may add a recorded **Result summary**.

## Check labels

| Label | Meaning |
|-------|---------|
| `[config]` | EOS `show` commands, listener presence, template contract |
| `[live]` | Real handshake, API call, AAA test, or traffic probe (non-probe-client checks) |
| `[live / test-runner]` | Live probe executed from the test-runner container (default `PROBE_CLIENT`) |
| `[live / radius]` | Live probe executed from the radius container (`PROBE_CLIENT=radius`) |
| `[live / host]` | Live probe executed on the host (`PROBE_CLIENT=host`) |
| `[kme]` | Check executed inside a KME container (`make test-kme` / `make test-macsec-qkd`) |
| `[host]` | Check from a cEOS SAE client to a KME (`make test-kme`) |
| `[log]` | Syslog or container-log assertion (`make test-macsec-qkd`) |
| `[keys]` | Static SAK / key-mapping check (`make test-macsec-qkd`) |
| `WARN` | Check completes with a caveat (for example classical KEX); this is not proof of PQC safety |
| `SKIP` | Check cannot establish the result (for example no sample or no listener); not a failure |

## Suite summary line

Each `make test-*` target ends with a one-line summary that counts individual checks (`[config]`, `[live]`, `[live / test-runner]`, etc.):

```text
OpenConfig: ✓ - 99 passed, 15 warnings, 9 skipped
HOSTS: ✓ - 12 passed
RadSec: ✓ - 23 passed
```

| Part | Meaning |
|------|---------|
| **Name** | Suite label (e.g. `OpenConfig`, `RadSec`, `HOSTS`) |
| **✓ / ✗** | Overall outcome - **✓** when no check failed; **✗** when the suite aborts |
| **passed** | Checks that completed successfully |
| **warnings** | Checks marked **WARN** (e.g. classical wire KEX) - still a pass |
| **failed** | Shown only when failed checks were recorded before abort |
| **skipped** | Checks marked **SKIP** (platform limitation - not a failure) |

Only non-zero buckets are shown. On failure the summary is printed to stderr, e.g. `OpenConfig FAILED: ✗ - <first error>`.

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

Results reflect the default **EOS 4.37.0F** (`CEOS_IMAGE=ceos:4.37.0F`; see [Setup](../setup.md)), verified on three ARM64 cEOS switches over IPv4 and IPv6 unless noted, with QuaDRA **1.0.10.rel1**. These results describe this lab, not a hardware qualification.

| Suite | Result on 4.37.0F |
|-------|------------------|
| SSH | 9 passed |
| eAPI | 15 passed |
| RadSec | 23 passed |
| Syslog | 15 passed |
| OpenConfig | 99 passed, 15 warnings, 9 skipped |
| KME | 9 passed |
| Dynamic MACsec | 17 passed |
| QuaDRA / QKD | 15 passed |
| Extended MACsec reauthentication | 22 passed |
| Settled host routing | 12 routes passed |

The **15 OpenConfig warnings** are gRIBI TLS/RPC checks (12) and eos-sdk-rpc IPv4 checks (3). The **nine skips** are gNPSI Subscribe without packets (6) and eos-sdk-rpc IPv6 without a listener (3). Warnings and skips do not establish PQC-safe application operation. Historical comparisons and test changes are recorded in the [Changelog](../changelog.md).

## Result summary

Recorded **live** behavior on **EOS 4.37.0F** (3 switches, IPv4 + IPv6 unless noted).

| Service | Make target | TLS 1.3 observed | KEX configured | KEX used (live) | PQC-safe |
|---------|-------------|---------------------|----------------|-----------------|----------|
| SSH | `test-ssh` | N/A (SSH, not TLS) | `mlkem768x25519-sha256` | `mlkem768x25519-sha256` | Yes |
| eAPI | `test-eapi` | Yes | `X25519MLKEM768` | `X25519MLKEM768` | Yes |
| gNMI | `test-openconfig` | Yes | `X25519MLKEM768` | `X25519MLKEM768` | Yes |
| gNOI (transport + RPC) | `test-openconfig` | Yes | `X25519MLKEM768` | `X25519MLKEM768` | Yes |
| gRIBI | `test-openconfig` | Yes | `X25519MLKEM768` | classical (`secp256r1`) | No |
| gNSI Certz | `test-openconfig` | Yes | `X25519MLKEM768` | `X25519MLKEM768` | Yes |
| gNPSI (TLS) | `test-openconfig` | Yes | `X25519MLKEM768` | `X25519MLKEM768` | Yes |
| gNPSI (Subscribe) | `test-openconfig` | Transport only | `X25519MLKEM768` | - (no packet received) | Unverified |
| RESTCONF | `test-openconfig` | Yes | `X25519MLKEM768` | `X25519MLKEM768` | Yes |
| RadSec | `test-radsec` | Yes | `X25519MLKEM768` | `X25519MLKEM768` | Yes |
| Syslog (EOS to collector) | `test-syslog` | Yes | `X25519MLKEM768` (+ classical fallback) | `X25519MLKEM768` | Yes |
| eos-sdk-rpc (IPv4) | `test-openconfig` | Yes | `X25519MLKEM768` | classical (`secp256r1`) | No |
| eos-sdk-rpc (IPv6) | `test-openconfig` | SKIP | `X25519MLKEM768` | - (no listener) | - |
| Syslog collector probe | `test-syslog` | Yes | `X25519MLKEM768` (+ classical fallback) | `X25519MLKEM768` | Yes |

**Columns**

| Column | Meaning |
|--------|---------|
| **TLS 1.3 observed** | Live session uses TLS 1.3 (or SSH for port 22). **Yes** records the positive probe; it does not assert rejection of TLS 1.2 or classical offers. See the service notes below. |
| **KEX configured** | Key-establishment group(s) in EOS `ssl profile` or `management ssh` config (what the switch is configured to offer). |
| **KEX used (live)** | Group negotiated on the wire during the listed make target. |
| **PQC-safe** | **Yes** when the live KEX is the lab hybrid (`X25519MLKEM768` or `mlkem768x25519-sha256`); **No** when classical KEX is used or PQC negotiation fails. **Unverified** means no successful application data check; **`WARN`** in suite output is not a PQC-safe value. |
| **SKIP** | Result not established because of a platform/config limitation or missing data; not proof of success. |

**Notes**

- **Syslog:** All six EOS-to-collector connections selected hybrid group **4588**, with delivery verified using unique per-run markers. Classical fallback remains configured; hybrid-only enforcement was not tested.
- **gNPSI:** Hybrid mTLS and reflection pass. Classical TLS 1.3 and TLS 1.2 are rejected. Subscribe data reception is **unverified**, with six **SKIPs**; successful reflection alone does not prove a working stream.
- **gRIBI:** Hybrid-only mTLS fails; `secp256r1` TLS 1.3 and Get RPC work. Separate TLS 1.2 probes also complete despite the strict profile.
- **eos-sdk-rpc (IPv4):** Hybrid-only probe gets EOF; explicit `secp256r1` completes TLS 1.3. TLS 1.2 negotiates then ends with EOF, which is not a verified application session.
- **eos-sdk-rpc (IPv6):** Native IPv6 connections refuse on 9543 with `local interface Management0`. Socket inspection shows an IPv4-mapped bind; IPv4 mTLS and IPv6 eAPI controls succeed on all three switches. Alternative binding configurations were not evaluated.
- **RESTCONF:** Hybrid positive probes pass, but classical TLS 1.3 and TLS 1.2 also complete despite the strict profile. This policy gap is outside the standard suite’s positive handshake assertion.

## Test guides

Same order as `make test-lab`:

| Guide | Target | Covers |
|-------|--------|--------|
| [SSH](ssh.md) | `make test-ssh` | Management SSH PQC KEX |
| [eAPI](eapi.md) | `make test-eapi` | HTTPS + JSON-RPC PQC |
| [RadSec](radsec.md) | `make test-radsec` | Reachability, AAA, collector TLS |
| [Syslog](syslog.md) | `make test-syslog` | TLS delivery + collector PQC |
| [OpenConfig connectivity](openconfig.md) | `make test-openconfig` | gNMI, gNOI, gRIBI, gNSI, gNPSI, RESTCONF, eos-sdk-rpc |
| [KME (ETSI QKD 014)](kme.md) | `make test-kme` | SAE status + enc/dec round-trip |
| [MACsec 802.1X](macsec-dot1x.md) | `make test-macsec-dot1x` | Dynamic MACsec (EAP-TLS + MKA); optional `test-macsec-dot1x-reauth` |
| [MACsec QuaDRA QKD](macsec-qkd.md) | `make test-macsec-qkd` | Static SAK / QKD rotation (skips when extension absent) |
| [Host routing](hosts.md) | `make test-hosts` | Data-plane ping matrix |

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
