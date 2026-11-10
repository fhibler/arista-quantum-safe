# MACsec 802.1X tests

`make test-macsec-dot1x` runs `python -m lab.test_macsec_dot1x` on the **ceos1-both <-> ceos2-pqc** Ethernet1 link (dynamic MACsec via 802.1X EAP-TLS + MKA).

Optional extended reauth wait: `make test-macsec-dot1x-reauth` (`VERIFY_REAUTH=1`): **75 s fixed wait**, or up to **103 s** including paired MKA retry delays, plus command time and baseline checks.

**Wait times:** MKA agreement allows **15 paired attempts**, **2 s apart** (**28 s maximum retry delays**). A converged check returns immediately; reauth adds its separate wait and MKA check. Commands add runtime. Static MACsec on the ceos1-both ↔ ceos3-qkd link is covered by [MACsec QuaDRA QKD tests](macsec-qkd.md). See [Wait times](index.md#wait-times).

**Policy:** The RADIUS EAP-TLS tunnel uses PQC-hybrid **`X25519MLKEM768`**. MACsec frame encryption uses MKA-derived keys (separate layer).

## What is checked

### Authenticator (ceos1-both)

| Check | Type | Method |
|-------|------|--------|
| dot1x + macsec config | `[config]` | Running-config: authenticator, reauth period, `mac security profile dynamic` |
| 802.1X host state | `[live]` | `show dot1x hosts` → identity SUCCESS |
| Port authorization | `[live]` | `show dot1x interface Ethernet1 detail` → Authorized |
| MKA peers | `[live]` | `show mac security participants interface Ethernet1 detail` |
| MACsec status | `[live]` | Traffic protected, active key |
| CKN match | `[live]` | Same connectivity association key as supplicant |

### Supplicant (ceos2-pqc)

| Check | Type | Method |
|-------|------|--------|
| Supplicant config | `[config]` | EAP-TLS + ssl profile DOT1X |
| 802.1X status | `[live]` | `show dot1x supplicant` → success, tls |
| PQC in EAP-TLS | `[live]` | Output contains `X25519MLKEM768` |
| MKA / MACsec | `[live]` | Matching CKN, protected traffic |

### Inter-switch connectivity

| Check | Type | Method |
|-------|------|--------|
| Protected path ping | `[live]` | Ping across the MACsec-protected /30 (`10.255.0.1` ↔ `10.255.0.2`) |

### Optional reauth (`VERIFY_REAUTH=1`)

| Check | Type | Method |
|-------|------|--------|
| Port still authorized | `[live]` | Wait 75 s; `show dot1x` still Authorized; paired MKA retries can add up to 28 s plus command time |
| Matching CKN | `[live]` | Peers still agree (CKN may rotate - new EAP-TLS MSK) |
| RADIUS Login OK | `[live]` | Extra `Auth: Login OK` in radius log |

## Pass criteria

- 802.1X authenticated on both sides
- MKA live peers with **matching CKN**
- MACsec interface reports traffic **protected**
- Inter-switch ping succeeds
- With `test-macsec-dot1x-reauth`: port stays Authorized, peers still match on CKN, RADIUS `Login OK` count increases

The CKN comparison samples both peers together and retries up to 15 times, two seconds apart.
Periodic 802.1X reauthentication can rotate the CKN and briefly select different principal
MKA participants on each switch. Both the normal and extended reauth checks wait for
agreement; a persistent mismatch or missing live peers still fails.

## Manual reproduction

```bash
# 802.1X
docker exec -i arista-quantum-safe-ceos1-both Cli <<'EOF'
enable
show dot1x hosts
show dot1x interface Ethernet1 detail
EOF

docker exec -i arista-quantum-safe-ceos2-pqc Cli <<'EOF'
enable
show dot1x supplicant
EOF

# MKA / MACsec
docker exec -i arista-quantum-safe-ceos1-both Cli <<'EOF'
enable
show mac security participants interface Ethernet1 detail
show mac security interface Ethernet1 detail
EOF

# Protected path ping
docker exec -i arista-quantum-safe-ceos1-both Cli <<'EOF'
enable
ping 10.255.0.2 repeat 3
EOF
```

Configuration reference: [MACsec service](../services/macsec.md) (802.1X section).

Related: [RadSec tests](radsec.md) (EAP-TLS backend), [MACsec QuaDRA QKD tests](macsec-qkd.md) (static SAK on Ethernet2).

<- [Test suite overview](index.md)
