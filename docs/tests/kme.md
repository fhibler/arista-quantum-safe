# KME (ETSI QKD 014) tests

`make test-kme` runs `python -m lab.test_kme` — SAE status, peer domain, enc/dec round-trip inside KME containers, and strict TLS chain verify from cEOS SAE clients.

QuaDRA static SAK / MACsec rotation is separate: **`make test-macsec-qkd`**.

## What is checked

| Check | Method |
|-------|--------|
| kme-a SAE status | Inside `kme-a` container — locked SAE ID, peer link |
| kme-b peer status | Inside `kme-b` container |
| enc/dec round-trip | `enc_keys` on kme-a → `dec_keys` on kme-b (32-byte key) |
| cEOS SAE TLS | Strict chain verify from **ceos1-both** and **ceos3-qkd** to both KME HTTPS APIs |

## Pass criteria

- Both KME simulators report healthy SAE/peer state
- Key material round-trips between kme-a and kme-b
- cEOS nodes verify KME server certificates with lab PKI

## Manual reproduction

```bash
make test-kme

docker exec arista-quantum-safe-ceos1-both ip netns exec ns-MGMT curl -sf \
  --tlsv1.3 --tls-max 1.3 \
  --cacert /mnt/flash/kme-ca.crt.pem \
  --cert /mnt/flash/kme-sae.crt.pem --key /mnt/flash/kme-sae.key.pem \
  https://172.20.127.51:8010/api/v1/keys/25840139-0dd4-49ae-ba1e-b86731601803/status
```

Configuration reference: [QKD / ETSI 014 service](../services/qkd-etsi014.md).

Related: [MACsec QuaDRA QKD tests](macsec-qkd.md), [Test suite overview](index.md).
