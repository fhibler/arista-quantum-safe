# MACsec

Dynamic **802.1X EAP-TLS + MKA** MACsec protects the **ceos1-both ↔ ceos2-pqc** inter-switch link on **Ethernet1** (`10.255.0.1/30` ↔ `10.255.0.2/30`).

## Configuration

| Role | Node | Interface |
|------|------|-----------|
| Authenticator | ceos1-both | Ethernet1 |
| Supplicant | ceos2-pqc | Ethernet1 |

### Authenticator (ceos1-both)

```text
aaa authentication dot1x default group RADIUS
dot1x system-auth-control
!
interface Ethernet1
   dot1x pae authenticator
   dot1x reauthentication
   dot1x timeout reauth-period 60
   mac security profile dynamic
```

802.1X uses RadSec AAA group **RADIUS** (PQC-hybrid TLS to FreeRADIUS).

### Supplicant (ceos2-pqc)

```text
dot1x pae supplicant macsec-sp
   identity ceos2-pqc
   eap-method tls
   ssl profile DOT1X
!
interface Ethernet1
   dot1x pae supplicant macsec-sp
   mac security profile dynamic
```

Ssl profile **`DOT1X`** restricts EAP-TLS to **`X25519MLKEM768`**.

### MKA / MACsec

Profile **`dynamic`** derives MACsec keys from the EAP-TLS session (FreeRADIUS policy copies `EAP-Session-Id` → `EAP-Key-Name` on Access-Accept).

## Caveats

| Topic | Status on cEOS 4.36.1F |
|-------|------------------------|
| EAP-TLS KEX | **PQC-safe** (`X25519MLKEM768` in supplicant detail) |
| MACsec keys | Derived from EAP — not direct PQC wire protocol on MACsec frames |
| Reauthentication | Period **60 s** — optional extended check via `make test-macsec-reauth` |
| Static SAK / QKD paths | Out of scope for public docs |

!!! note "Layer distinction"
    PQC applies to the **EAP-TLS tunnel** between supplicant and RADIUS server. MACsec encrypts the Ethernet link with keys derived from that exchange — verify EAP-TLS PQC separately from MACsec frame encryption.

## Verification

### 802.1X status

```bash
docker exec -i arista-quantum-safe-ceos1-both Cli <<'EOF'
enable
show dot1x hosts
show dot1x interface Ethernet1 detail
EOF

docker exec -i arista-quantum-safe-ceos2-pqc Cli <<'EOF'
enable
show dot1x supplicant
EOF
```

Expect host **SUCCESS**, port **Authorized**, supplicant status **success**, EAP method **tls**, PQC group in output.

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

Automated: `make test-macsec` (and `VERIFY_REAUTH=1 make test-macsec-reauth` for periodic reauth).

See [MACsec tests](../tests/macsec.md).

← [Services overview](index.md)
