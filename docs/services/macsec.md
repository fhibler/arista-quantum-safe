# MACsec

Dynamic **802.1X EAP-TLS + MKA** MACsec protects the **ceos1-both ↔ ceos2-pqc** inter-switch link on **Ethernet1** (`10.255.0.1/30` ↔ `10.255.0.2/30`).

| Item | Value |
|------|-------|
| Port | — (L2 link; no TCP/UDP port) |
| Profile | `DOT1X` (EAP-TLS supplicant ssl profile) |
| KEX | `X25519MLKEM768` in EAP-TLS tunnel |
| Template | `configs/ceos/ceos1-both.cfg.in`, `configs/ceos/ceos2-pqc.cfg.in` → `lab/.gen/` |
| AAA / RadSec | [RADIUS / RadSec](radius-radsec.md) (`RADSEC` profile) |

See also [Certificates and TLS 1.3](../misc/certificates-and-tls13.md).

## Configuration

| Role | Node | Interface |
|------|------|-----------|
| Authenticator | ceos1-both | Ethernet1 |
| Supplicant | ceos2-pqc | Ethernet1 |

### Authenticator (ceos1-both)

Complete relevant stanzas from `configs/ceos/ceos1-both.cfg.in`:

```text
aaa authentication dot1x default group RADIUS
aaa accounting dot1x default start-stop group RADIUS
!
dot1x system-auth-control
!
interface Ethernet1
   no switchport
   ip address 10.255.0.1/30
   ipv6 address 2001:db8:255:0::1/126
   mac security profile dynamic
   dot1x pae authenticator
   dot1x reauthentication
   dot1x port-control auto
   dot1x timeout reauth-period 60
!
mac security
   profile dynamic
      key source dot1x
!
radius-server host 172.20.127.50 vrf MGMT tls ssl-profile RADSEC
!
aaa group server radius RADIUS
   server 172.20.127.50 tls vrf MGMT
```

802.1X uses RadSec AAA group **RADIUS** (PQC-hybrid TLS to FreeRADIUS). See [RADIUS / RadSec](radius-radsec.md) for the complete `RADSEC` ssl profile.

### SSL profile `DOT1X` (supplicant)

Complete profile from `configs/ceos/ceos2-pqc.cfg.in`:

```text
management security
   ssl profile DOT1X
      tls versions 1.3
      key-establishment-group X25519MLKEM768
      cipher v1.3 TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256
      certificate ceos2-pqc-client.pem key ceos2-pqc-client.key
      trust certificate radsec-ca.pem
```

### Supplicant service binding (ceos2-pqc)

```text
dot1x system-auth-control
!
dot1x
   supplicant profile macsec-sp
      identity ceos2-pqc
      eap-method tls
      ssl profile DOT1X
!
interface Ethernet1
   no switchport
   ip address 10.255.0.2/30
   ipv6 address 2001:db8:255:0::2/126
   mac security profile dynamic
   dot1x pae supplicant macsec-sp
!
mac security
   profile dynamic
      key source dot1x
```

### MKA / MACsec key derivation

Profile **`dynamic`** derives MACsec keys from the EAP-TLS session (FreeRADIUS policy copies `EAP-Session-Id` → `EAP-Key-Name` on Access-Accept).

## Caveats

| Topic | Status on EOS |
|-------|------------------------|
| Config | `DOT1X` profile lists `X25519MLKEM768` |
| Live wire (EAP-TLS) | **PQC-safe** (`X25519MLKEM768` in supplicant detail) |
| MACsec keys | Derived from EAP — not direct PQC wire protocol on MACsec frames |
| Reauthentication | Period **60 s** — optional extended check via `make test-macsec-dot1x-reauth` |
| Static SAK / QKD paths | Out of scope for this page — see [QKD / ETSI 014](qkd-etsi014.md) |

!!! note "Layer distinction"
    PQC applies to the **EAP-TLS tunnel** between supplicant and RADIUS server. MACsec encrypts the Ethernet link with keys derived from that exchange — verify EAP-TLS PQC separately from MACsec frame encryption.

## Verification

### Configuration

```bash
docker exec -i arista-quantum-safe-ceos2-pqc Cli <<'EOF'
enable
show management security ssl profile DOT1X detail
show dot1x supplicant
EOF
```

```bash
docker exec -i arista-quantum-safe-ceos1-both Cli <<'EOF'
enable
show dot1x hosts
show dot1x interface Ethernet1 detail
EOF
```

Expect host **SUCCESS**, port **Authorized**, supplicant status **success**, EAP method **tls**, PQC group in output.

### Live PQC (802.1X / EAP-TLS)

Supplicant ssl profile detail should show `X25519MLKEM768`. RadSec and EAP-TLS paths are covered by `make test-macsec-dot1x` and `make test-radsec`.

### MKA / MACsec

```bash
docker exec -i arista-quantum-safe-ceos1-both Cli <<'EOF'
enable
show mac security participants interface Ethernet1 detail
show mac security interface Ethernet1 detail
EOF
```

Expect live MKA peers, matching **CKN** on both sides, traffic **protected**.

### Data-plane reachability

```bash
docker exec -i arista-quantum-safe-ceos1-both Cli <<'EOF'
enable
ping 10.255.0.2 repeat 3
EOF
```

Automated: `make test-macsec-dot1x` (and `VERIFY_REAUTH=1 make test-macsec-dot1x-reauth` for periodic reauth).

See [MACsec 802.1X tests](../tests/macsec-dot1x.md). QuaDRA static SAK: [MACsec QuaDRA QKD tests](../tests/macsec-qkd.md).

## Other remarks

There are no other remarks.

<- [Services overview](index.md)
