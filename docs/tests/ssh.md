# SSH tests

`make test-ssh` runs `python -m lab.test_ssh` against all three EOS nodes (**ceos1-both**, **ceos2-pqc**, **ceos3-qkd**) on **IPv4 and IPv6**.

**Policy:** OpenSSH KEX **`mlkem768x25519-sha256`** on VRF MGMT only (default VRF SSH disabled).

SSH probes run from **`arista-quantum-safe-test-runner`** by default. Override with `PROBE_CLIENT=host` when debugging (devcontainer with OpenSSH 10+).

## What is checked

| Check | Type | Method |
|-------|------|--------|
| `management ssh` KEX and ciphers | `[config]` | `show running-config section management ssh` |
| SSH server VRF binding | `[config]` | `show management ssh vrf MGMT` / default VRF |
| Live SSH session | `[live / test-runner]` | SSH to switch mgmt with PQC KEX only |

## Pass criteria

Exit 0, output contains `kex: algorithm: mlkem768x25519-sha256` and hostname JSON.

## Manual reproduction

```bash
docker exec arista-quantum-safe-test-runner sh -c \
  'ssh -vvv \
     -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
     -o PubkeyAuthentication=no -o PreferredAuthentications=keyboard-interactive \
     -o KexAlgorithms=mlkem768x25519-sha256 \
     admin@172.20.127.11 "show hostname | json" 2>&1' \
  | grep "kex: algorithm"
```

Configuration reference: [SSH service](../services/ssh.md).

See [Test suite overview](index.md#result-summary) for expected live KEX on **EOS 4.36.2F**.
