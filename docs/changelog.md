# Changelog

Verified lab changes are summarized by **target EOS version**, newest first. Each entry identifies the previous version and uses the same sections: **Versions**, **Behavior changes**, **Test results**, **Known limitations**, **Test and tooling changes**, and **Verification scope**.

For a future upgrade, add a new `## EOS <version>` entry above the existing entries and reuse those six sections. Compare against the previous default using the same configuration, tools, and assertions; explain any changes that prevent a direct comparison. Keep historical results here and replace the results in service and test guides with the latest verified values. Entries record observed lab behavior, not a vendor release-note changelog.

For each limitation, state the verified behavior followed by the remaining failure or verification gap. Distinguish successful hybrid negotiation from policy enforcement. Use **unverified** for outcomes not established, **not measured** for missing measurements, **not tested** for configurations not exercised, and **not revalidated** for earlier findings not checked again.

## EOS 4.37.0F

### Versions

Upgrade from **EOS 4.36.2F** to **EOS 4.37.0F**.

| Component | Previous | Current |
|-----------|----------|---------|
| Default cEOS image | `ceos:4.36.2F` | `ceos:4.37.0F` |
| EOS bundled OpenSSL | 3.2.2 | **3.5.5** |
| Peer/probe OpenSSL | 3.5.9 | 3.5.9 (same images) |
| QuaDRA | 1.0.10.rel1 | 1.0.10.rel1 (same extension) |

Both EOS images are ARM64. Peer/probe containers pin Alpine **3.24**; apk OpenSSL patch releases float independently of the EOS bundled library.

### Behavior changes

| Finding | 4.36.2F | 4.37.0F |
|---------|---------|---------|
| EOS → syslog selected KEX | Classical `x25519` | **`X25519MLKEM768`** |
| gNPSI TLS / reflection KEX | Classical `secp256r1` | **`X25519MLKEM768`**, all six endpoints |
| gNPSI classical TLS 1.3 offer | Accepted | **Rejected** |
| gNPSI TLS 1.2 offer | Negotiates, then EOF | **Rejected before handshake** |

Syslog hybrid KEX and gNPSI hybrid TLS/reflection were verified on all three switches over IPv4 and IPv6 without changing their profiles. gNPSI Subscribe sample delivery remains **unverified**; policy enforcement results are recorded under [Known limitations](#known-limitations).

SSH, eAPI JSON-RPC, gNMI GET/mTLS, gNOI Ping/reflection, gNSI Certz, RadSec, and EAP-TLS continued to negotiate hybrid KEX. Dynamic MACsec encryption and reauthentication, KME round trips and certificate-chain checks, QuaDRA roles/SAK cross-mapping/key delivery, and settled host routing continued to pass.

Both QuaDRA master/slave IPv4 TLS connections select **TLS 1.3 / `X25519MLKEM768` / `TLS_AES_256_GCM_SHA384`** during normal key rotation. QuaDRA KEX was not measured on the previous image.

### Test results

Final results use the corrected assertions on both versions. Passing functional checks do not establish unmeasured TLS KEX or untested policy enforcement; the remaining gaps are recorded under [Known limitations](#known-limitations).

| Suite | 4.36.2F | 4.37.0F |
|-------|---------|---------|
| SSH | 9 passed | 9 passed |
| eAPI | 15 passed | 15 passed |
| RadSec | 23 passed | 23 passed |
| Syslog | 9 passed, 6 warnings | **15 passed** |
| OpenConfig | 87 passed, 27 warnings, 9 skipped | **99 passed, 15 warnings, 9 skipped** |
| KME | 9 passed | 9 passed |
| Dynamic MACsec | 17 passed | 17 passed |
| QuaDRA / QKD | 15 passed | 15 passed |
| QuaDRA with passive TLS measurement | Not measured | **17 passed**, both IPv4 clients hybrid |
| Extended MACsec reauthentication | 22 passed | 22 passed |
| Settled host routing | 12 routes passed | 12 routes passed |

The MACsec/QuaDRA counts in this comparison predate moving static MACsec configuration, convergence, and ping checks from `test-macsec-dot1x` into `test-macsec-qkd`.

Offline upgrade verification also passed **588 pytest tests**, including Containerlab checks.

### Known limitations

The following service failures and verification gaps remain after the upgrade:

- **gNPSI Subscribe:** Hybrid TLS/reflection succeeds. Subscribe sample delivery remains **unverified** (six SKIPs): no JSON `Sample.packet` arrived, including during a separate 75-second sustained traffic run from three hosts. On 4.37.0F, all switches reported zero sFlow samples and zero gNPSI received datagrams.
- **gRIBI:** Classical `secp256r1` TLS 1.3 and Get RPC succeed; hybrid-only mTLS fails. Hybrid-only and TLS 1.3-only policy enforcement **fails**: classical TLS 1.3 and TLS 1.2 complete despite the strict profile.
- **eos-sdk-rpc:** Classical `secp256r1` TLS 1.3 succeeds over IPv4; hybrid-only mTLS fails. TLS 1.2 negotiates parameters then ends with EOF, leaving application operation over TLS 1.2 **unverified**. The current `local interface Management0` binding has no native IPv6 listener (three SKIPs). Direct socket inspection and TCP/mTLS probes confirmed the IPv4-mapped bind on all three upgraded switches; IPv6 eAPI succeeded as a connectivity control. Alternative bindings were **not tested**.
- **RESTCONF:** Hybrid TLS 1.3 succeeds. Hybrid-only and TLS 1.3-only policy enforcement **fails**: separate probes confirm that classical TLS 1.3 and TLS 1.2 also complete despite the strict profile.
- **Syslog:** Hybrid TLS 1.3 succeeds. Hybrid-only policy enforcement with a changed configuration was **not tested**.
- **QuaDRA:** Both actual client paths now have measured hybrid TLS KEX. Classical groups are also advertised; hybrid-only enforcement remains **unverified**. Simulator peer TLS KEX was **not measured**.
- **Routing:** Settled reruns pass all 12 directed IPv4/IPv6 routes. Both versions show temporary loss during initialization.
- **gNSI / shared-port clients:** The `transport gnmi default` binding and the gnoic, gnmic, and gnsic clients on port 6030 are verified. Earlier 4.36.2F rejection of `transport grpc default` and the grpcurl handshake failure on port 6030 were **not revalidated** on 4.37.0F. grpcurl reflection on gNPSI port 6031 succeeds; Subscribe sample delivery remains **unverified**.
- **Other cryptographic capabilities:** Standalone ML-KEM and post-quantum certificate/signature capabilities were **not revalidated**.

The remaining **15 OpenConfig warnings** on 4.37.0F are gRIBI TLS/RPC checks (12) and eos-sdk-rpc IPv4 checks (3). Its **nine skips** are gNPSI Subscribe (6) and eos-sdk-rpc IPv6 (3).

### Test and tooling changes

- `make test-quadra-tls` adds passive capture of both actual QuaDRA clients, checks final ServerHello selection and fresh successful key delivery, and retains packet/decoded evidence. Missing evidence and non-hybrid selection fail the check.
- Syslog checks now verify negotiated hybrid KEX and delivery of fresh messages.
- gNPSI Subscribe requires an actual JSON `Sample.packet` on stdout and checks RPC/JSON errors. The former probe incorrectly counted stderr `Terminated` as a datagram and masked RPC failures; earlier claims of successful streaming are withdrawn. Subscribe sample delivery remains **unverified**.
- Reauthentication recognizes RADIUS request IDs such as `Auth: (59) Login OK`. MKA extraction prefers the successful `principalActor` when retained participants coexist.
- The eAPI failure-test mock intercepts the actual TLS helper, avoiding unintended live connections.
- The devcontainer Python image is pinned to **`3.14-trixie`** to avoid the autopep8 extension crash under Python 3.15.

### Verification scope

Both images were deployed on three ARM64 cEOS switches with the same templates, peer images, probe tools, and QuaDRA extension. Both archive SHA-512 checks passed. This is a lab comparison, not a hardware qualification.

A separate TLS matrix exercised **108 probes per image**. All **18 changed outcomes** in that matrix were gNPSI. EOS-originated syslog was verified separately.

Image smoke checks, Containerlab dry-run, topology validation, public export, site configuration synchronization, and strict documentation build also passed. Service failures, verification gaps, and earlier findings that were **not revalidated** are recorded under [Known limitations](#known-limitations).

Current operational references: [Services](services/index.md) and [Test results](tests/index.md#result-summary).
