# Host routing tests

`make test-hosts` runs `python -m lab.test_hosts` — alpine host ping across all off-diagonal data-plane pairs on **IPv4 and IPv6**.

## What is checked

| Check | Method |
|-------|--------|
| Host-to-host reachability | `ping` from each `host1` / `host2` / `host3` container to every other host's data-plane address |
| Summary matrix | Combined IPv4/IPv6 ping matrix (each cell shows both families) |

Six directed pairs per family (12 live checks total):

- host1 ↔ host2, host1 ↔ host3, host2 ↔ host3 (both directions)

## Pass criteria

- All off-diagonal ping pairs succeed for IPv4 and IPv6
- Summary line: `HOSTS: ✓ — all data-plane ping pairs reachable (IPv4 and IPv6)`

## Manual reproduction

```bash
make test-hosts

docker exec arista-quantum-safe-host1 ping -c3 10.0.2.1
docker exec arista-quantum-safe-host1 ping -6 -c3 2001:db8:2::1
```

Related: [Test suite overview](index.md).
