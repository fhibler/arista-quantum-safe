# Changelog

Entries record measured lab results by target EOS version, newest first. Keep release comparisons here; service and test guides describe only the tested version on the main page. These observations do not establish vendor bug closure or hardware qualification.

## EOS 4.37.0F

### Versions

| Component | Comparison baseline | Target |
|-----------|---------------------|--------|
| cEOS ARM64 | `ceos:4.36.2F` | `ceos:4.37.0F` |
| EOS OpenSSL | 3.2.2 | 3.5.5 |

Peer/probe OpenSSL **3.5.9** and QuaDRA **1.0.10.rel1** were the same for both images.

### Behavior changes

| Measurement | 4.36.2F | 4.37.0F |
|-------------|---------|---------|
| EOS → syslog selected KEX | `x25519` | `X25519MLKEM768` |
| gNPSI TLS / reflection KEX | `secp256r1` | `X25519MLKEM768` |
| gNPSI classical TLS 1.3 offer | Accepted | Rejected |
| gNPSI TLS 1.2 offer | Parameters negotiated, then EOF | Rejected before handshake |

These measurements cover three switches over IPv4 and IPv6 with unchanged TLS profiles. Syslog explicitly permits classical fallback.

### Test results

| Suite | 4.36.2F | 4.37.0F |
|-------|---------|---------|
| Syslog | 9 passed, 6 warnings | 15 passed |
| OpenConfig, same configuration | 87 passed, 27 warnings, 9 skipped | 99 passed, 15 warnings, 9 skipped |
| OpenConfig, Ethernet8 sFlow source and two-second polling | **Not tested** | 105 passed, 15 warnings, 3 skipped |

Subscribe delivers datagrams on all six endpoints with the explicit source and polling settings. Actual Subscribe connections select **TLS 1.3 / `X25519MLKEM768` / `TLS_AES_128_GCM_SHA256`**. Both QuaDRA IPv4 client paths select hybrid TLS with fresh key delivery; previous-image QuaDRA KEX was **not measured**.

### Known limitations

- **gRIBI / eos-sdk-rpc:** Hybrid-only mTLS fails; classical TLS 1.3 succeeds. gRIBI also accepts TLS 1.2. eos-sdk-rpc TLS 1.2 ends in EOF; application operation is **unverified**. Its Management0 binding has no native IPv6 listener.
- **RESTCONF:** Accepts hybrid and classical TLS 1.3, plus TLS 1.2, despite the strict profile.
- **Syslog / QuaDRA:** Hybrid negotiation is measured; hybrid-only enforcement is **not tested** for syslog and **unverified** for QuaDRA. Simulator peer TLS KEX was **not measured**.

### Test and tooling changes

Subscribe requires a nonempty decoded `Sample.packet`; empty streams and RPC/JSON/base64 errors fail. Earlier success claims based on stderr `Terminated` are withdrawn. Static MACsec checks are assigned to `test-macsec-qkd`. Counts predating that assignment were MACsec **17 / 22** (baseline / reauthentication) and QuaDRA **15 / 17** (functional / TLS); current runs report **9 / 13** and **19 / 21** passed, respectively. Wait notices are excluded from check counts.

### Verification scope

Three ARM64 cEOS switches, both IP families unless noted; **108 TLS diagnostics per image**, with all **18 changed outcomes** on gNPSI. The explicit sFlow source/polling configuration was tested only on 4.37.0F. Current operational references: [Services](services/index.md) and [Test results](tests/index.md#result-summary).
