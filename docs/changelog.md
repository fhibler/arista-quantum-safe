# Changelog

Verified lab changes are grouped by **target EOS version**, newest first. Each entry identifies the previous version and uses the same sections: **Versions**, **Behavior changes**, **Test results**, **Known limitations**, **Test and tooling changes**, and **Verification scope**.

For a future upgrade, add a new `## EOS <version>` entry above the existing entries and reuse those six sections. Compare against the previous default using the same configuration, tools, and assertions; explain any changes that prevent a direct comparison. Mark untested behavior **not revalidated**, and distinguish measured hybrid support from rejection of weaker offers. Keep historical results here and replace the results in service and test guides with the latest verified values. Entries record observed lab behavior, not a vendor release-note changelog.

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
| EOS → syslog selected KEX | Classical `x25519` (29) | **`X25519MLKEM768` (4588)**, all six connections |
| gNPSI TLS / reflection KEX | Classical `secp256r1` | **`X25519MLKEM768`**, all six endpoints |
| gNPSI classical TLS 1.3 offer | Accepted | **Rejected** |
| gNPSI TLS 1.2 offer | Negotiates, then EOF | **Rejected before handshake** |

Syslog and gNPSI improvements were verified on all three switches over IPv4 and IPv6 without changing their profiles. The upgraded syslog ClientHello offers `4588,29`; the collector's **ServerHello selects 4588**. ClientHello offers alone do not establish the negotiated group. Classical fallback remains configured on both syslog peers.

SSH, eAPI JSON-RPC, gNMI GET/mTLS, gNOI Ping/reflection, gNSI Certz, RadSec, and EAP-TLS continued to negotiate hybrid KEX. Dynamic MACsec encryption and reauthentication, KME round trips and certificate-chain checks, QuaDRA roles/SAK cross-mapping/key delivery, and settled host routing continued to pass.

### Test results

Final results use the corrected assertions on both versions.

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
| Extended MACsec reauthentication | 22 passed | 22 passed |
| Settled host routing | 12 routes passed | 12 routes passed |

Offline upgrade verification also passed **588 pytest tests**, including Containerlab checks, in an isolated checkout so generated PKI/topology fixtures could not disturb the live lab.

### Known limitations

These findings were present in both versions:

- **gNPSI Subscribe:** No JSON `Sample.packet` arrived, including during a separate 75-second sustained traffic run from three hosts. On 4.37.0F, all switches reported zero sFlow samples and zero gNPSI received datagrams. TLS/reflection are PQC-safe; sample delivery remains **unverified** (six SKIPs).
- **gRIBI:** Hybrid-only mTLS fails; classical `secp256r1` TLS 1.3 and Get RPC work. TLS 1.2 also completes despite the strict profile.
- **eos-sdk-rpc:** IPv4 remains classical (`secp256r1`). TLS 1.2 negotiates parameters then ends with EOF, which does not establish a successful application session. The current `local interface Management0` binding has no native IPv6 listener (three SKIPs). Direct socket inspection and TCP/mTLS probes confirmed the IPv4-mapped bind on all three upgraded switches; IPv6 eAPI succeeded as a connectivity control. Alternative bindings were not evaluated.
- **RESTCONF:** Hybrid TLS 1.3 succeeds, but classical TLS 1.3 and TLS 1.2 also complete despite the strict profile. The positive suite probe does not establish policy enforcement.
- **Syslog:** Both peers still permit classical fallback; a changed hybrid-only configuration was not tested.
- **KME / QuaDRA:** Functional and certificate-chain checks passed; TLS KEX was **not measured**.
- **Routing:** Both versions showed temporary loss during initialization; settled reruns passed all 12 directed IPv4/IPv6 routes.

The remaining **15 OpenConfig warnings** on 4.37.0F are gRIBI TLS/RPC checks (12) and eos-sdk-rpc IPv4 checks (3). Its **nine skips** are gNPSI Subscribe (6) and eos-sdk-rpc IPv6 (3).

### Test and tooling changes

- Syslog capture reads the **ServerHello selected group**, rather than ClientHello offers. Unique delivery markers prevent retained logs from satisfying later runs.
- gNPSI Subscribe requires an actual JSON `Sample.packet` on stdout and checks RPC/JSON errors. The former probe incorrectly counted stderr `Terminated` as a datagram and masked RPC failures; earlier claims of successful streaming are withdrawn.
- Reauthentication recognizes RADIUS request IDs such as `Auth: (59) Login OK`. MKA extraction prefers the successful `principalActor` when retained participants coexist.
- The eAPI failure-test mock intercepts the actual TLS helper, avoiding unintended live connections.
- The devcontainer Python image is pinned to **`3.14-trixie`** to avoid the autopep8 extension crash under Python 3.15.

The validated gNSI binding is `transport gnmi default`. Earlier 4.36.2F rejection of `transport grpc default` was **not revalidated** on 4.37.0F. Likewise, the earlier grpcurl handshake failure on shared port 6030 was **not revalidated**; use the verified gnoic, gnmic, and gnsic clients there. grpcurl reflection on gNPSI port 6031 succeeds; Subscribe data delivery remains unverified.

### Verification scope

Both images were deployed on three ARM64 cEOS switches with the same templates, peer images, probe tools, and QuaDRA extension. Both archive SHA-512 checks passed. This is a lab comparison, not a hardware qualification.

A separate TLS matrix exercised **108 probes per image**: six ports × three switches × two IP families × three explicit offers (hybrid TLS 1.3, classical TLS 1.3, classical TLS 1.2). All **18 changed outcomes** in that matrix were gNPSI. EOS-originated syslog was verified separately using fresh packet captures of the selected group.

Image smoke checks, Containerlab dry-run, topology validation, public export, site configuration synchronization, and strict documentation build also passed. Standalone ML-KEM and post-quantum certificate/signature capabilities were **not revalidated**.

Current operational references: [Services](services/index.md) and [Test results](tests/index.md#result-summary).
