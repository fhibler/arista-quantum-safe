# MACsec QuaDRA QKD tests

`make test-macsec-qkd` runs `python -m lab.test_macsec_qkd` — QuaDRA daemon health, static SAK cross-mapping on the **ceos1-both <-> ceos3-qkd** Ethernet2 link, and KME key-delivery log lines.

Skips with a warning when the QuaDRA extension (`.swix`) is not installed.

ETSI QKD 014 API checks (KME simulators) are separate: **`make test-kme`**.

## What is checked

| Check | Method |
|-------|--------|
| QuaDRA extension | `show extensions` (skip when absent) |
| Agent roles | `show daemon quadra` — **master** / **slave** |
| Static SAK profiles | Master tx ↔ slave rx key cross-mapping |
| Rotation syslog | `%QUADRA-4-ROTATION_SUCCESS%` when present (startup/recovery) |
| KME delivery | **enc_keys** on kme-a / **dec_keys** on kme-b container logs |
| Link reachability | Ping across QuaDRA /30 |

## Pass criteria

- Both switches report expected QuaDRA agent state (when extension installed)
- Static SAK profiles cross-map correctly
- KME log lines show key fetch/delivery activity (when QuaDRA active)

## Manual reproduction

```bash
make test-macsec-qkd    # skips when extension not installed

docker exec -i arista-quantum-safe-ceos1-both Cli <<'EOF'
enable
show extensions
show daemon quadra
show mac security profile quadra-master detail
show mac security interface Ethernet2
EOF
```

Configuration reference: [QKD / ETSI 014 service](../services/qkd-etsi014.md).

Related: [MACsec 802.1X tests](macsec-dot1x.md) (dynamic MACsec on Ethernet1), [Test suite overview](index.md).
