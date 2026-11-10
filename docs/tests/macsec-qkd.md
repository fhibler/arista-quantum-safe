# MACsec QuaDRA QKD tests

`make test-macsec-qkd` runs `python -m lab.test_macsec_qkd` on **ceos1-both:Ethernet2 ↔ ceos3-qkd:Ethernet1**. Static MACsec configuration, controlled ports, active keys, SAK cross-mapping, and bidirectional pings are always checked. When the QuaDRA extension is installed on both switches, the suite also checks daemon health and KME key-delivery log lines.

`make test-quadra-tls` adds passive TLS KEX measurement of the **actual QuaDRA clients** during normal key rotation. It captures both MGMT namespaces concurrently for 135 seconds, decodes the server-selected group with the test-runner's `tshark`, and requires fresh successful key requests from the captured source addresses. It does not generate substitute curl/OpenSSL connections or restart agents.

**Wait times:** each static MACsec convergence check allows **15 attempts**, **2 s apart** (**28 s maximum retry delays per switch**, **56 s combined**); converged checks return immediately. Ping/show command time is extra. The ordinary `test-macsec-qkd` checks have no intentional rotation wait. `test-quadra-tls` includes the static checks and expects **135 s of capture** for both clients concurrently. Its TLS phase allows a **250 s timeout budget**: capture + 15 s grace + two clients × (30 s decode + 20 s logs), with functional checks and process overhead extra. Changing `QUADRA_TLS_CAPTURE_SEC` changes the TLS phase budget to that value **+ 115 s**. See [Wait times](index.md#wait-times).

ETSI QKD 014 API checks (KME simulators) are separate: **`make test-kme`**.

## What is checked

| Check | Type | Method |
|-------|------|--------|
| Static MACsec config | `[config]` | Interface profile binding, static SAK source, `aes256-gcm-xpn` cipher; extension optional |
| Static MACsec status | `[live]` | Both controlled ports up with active keys; retry convergence; extension optional |
| QuaDRA extension | `[live]` | `show extensions` |
| Agent roles | `[live]` | `show daemon quadra` - **master** / **slave** |
| Static SAK profiles | `[keys]` | Master tx ↔ slave rx key cross-mapping; extension optional |
| Rotation syslog | `[log]` | `%QUADRA-4-ROTATION_SUCCESS%` when present (startup/recovery) |
| KME delivery | `[kme]` | **enc_keys** on kme-a / **dec_keys** on kme-b container logs |
| Link reachability | `[live]` | Bidirectional ping across QuaDRA /30; extension optional |
| QuaDRA TLS KEX (`test-quadra-tls`) | `[wire]` | Pair ClientHello with final ServerHello per TCP stream for ceos1-both → kme-a and ceos3-qkd → kme-b; correlate with fresh HTTP 200 key requests |

## Pass criteria

- Static profiles are bound to the expected interfaces; both controlled ports are up with active keys and bidirectional pings succeed
- Both switches report expected QuaDRA agent state (when extension installed on both)
- Static SAK profiles cross-map correctly
- KME log lines show key fetch/delivery activity (when QuaDRA active)
- With `test-quadra-tls`, both clients must have a complete TLS sample and successful key delivery within the capture window; every observed final ServerHello must select TLS 1.3 and **`X25519MLKEM768`** (4588 / `0x11ec`). Client offers and HelloRetryRequest do not satisfy this check.

Measured on **EOS 4.37.0F / QuaDRA 1.0.10.rel1**, ARM64: `make test-macsec-qkd` reports **19 passed**; `make test-quadra-tls` reports **21 passed**, including the 19 functional checks and two wire checks. Both runs have no warnings, failures, or skips.

Both IPv4 QuaDRA-to-KME connections select **TLS 1.3 / `X25519MLKEM768` / `TLS_AES_256_GCM_SHA384`**, with fresh successful key delivery. The clients also advertise classical groups. Hybrid-only enforcement remains **unverified**; this measurement does not qualify simulator peer TLS or alternate KME configurations.

## Expected SKIP / WARN

| Check | When |
|-------|------|
| Daemon / KME checks in `test-macsec-qkd` | **SKIP** when the QuaDRA extension (`.swix`) is not installed on both switches; static MACsec checks still run and failures fail the suite |
| Rotation syslog | **WARN** when `%QUADRA-4-ROTATION_SUCCESS%` is absent (startup/recovery only) |
| `test-quadra-tls` | **FAIL** if the extension/capture/decode is unavailable, a handshake or fresh successful request is missing, or a non-hybrid group is selected; missing evidence remains **unverified** |

## Manual reproduction

```bash
make test-macsec-qkd    # always checks static MACsec; skips daemon/KME checks without extension
make test-quadra-tls    # requires extension; passively waits for a normal rotation
# For a longer configured rotation interval:
make test-quadra-tls QUADRA_TLS_CAPTURE_SEC=255

docker exec -i arista-quantum-safe-ceos1-both Cli <<'EOF'
enable
show extensions
show daemon quadra
show mac security profile quadra-master detail
show mac security interface Ethernet2
EOF
```

Run the passive check without concurrent manual KME requests from the switches. The capture window must exceed the configured rotation interval; an existing session without a new handshake cannot establish KEX. No automatic reconnect or configuration change is performed.

Evidence is saved under **`lab/.gen/quadra-tls/`** (override `QUADRA_TLS_OUTPUT_DIR`): per-switch `.pcap`, `.tls.tsv`, `.tcpdump.log`, fresh `.requests.log`, and `result.json` containing selected group, cipher, source address, TCP stream, and ServerHello frame. Copy the directory before rerunning if retaining multiple runs. The test uses EOS `tcpdump`/`timeout` and the deployed test-runner's `tshark`; no host capture tools are required.

Configuration reference: [QKD / ETSI 014 service](../services/qkd-etsi014.md).

Related: [MACsec 802.1X tests](macsec-dot1x.md) (dynamic MACsec on Ethernet1).

<- [Test suite overview](index.md)
