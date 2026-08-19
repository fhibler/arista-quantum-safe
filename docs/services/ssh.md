# SSH

SSH on **VRF MGMT** uses OpenSSH-style **PQC-hybrid key exchange**, not TLS ssl profiles. NETCONF inherits the same SSH stack.

| Item | Value |
|------|-------|
| Port | **22** (SSH) |
| KEX | `mlkem768x25519-sha256` (not an ssl profile) |
| VRF | MGMT |
| Template | `configs/ceos/ceos*.cfg.in` → `lab/.gen/` |
| Certificates | Classical SSH host keys (unchanged by PQC policy) |

See also [Certificates and TLS 1.3](../misc/certificates-and-tls13.md).

## Configuration

### SSH security policy

Templates: `configs/ceos/ceos*.cfg.in` → `management ssh`

```text
management ssh
   key-exchange mlkem768x25519-sha256
   cipher aes256-gcm@openssh.com aes128-gcm@openssh.com chacha20-poly1305@openssh.com
   mac hmac-sha2-256 hmac-sha2-512
   shutdown
   !
   vrf MGMT
      no shutdown
```

| Setting | Value | Notes |
|---------|-------|-------|
| KEX | `mlkem768x25519-sha256` | ML-KEM-768 + X25519 hybrid |
| Ciphers | AEAD only | GCM / ChaCha20-Poly1305 |
| Default VRF | `shutdown` | SSH disabled outside MGMT |
| VRF MGMT | `no shutdown` | SSH listens on Management0 |

### NETCONF service binding

```text
management api netconf
   transport ssh default
      vrf MGMT
```

## Caveats

| Topic | Status on EOS |
|-------|------------------------|
| Config | Hybrid KEX listed and preferred |
| Live wire | **PQC-safe** — negotiates `mlkem768x25519-sha256` |
| Certificates | Classical host keys (unchanged by PQC policy) |

## Verification

### Configuration

```bash
docker exec -i arista-quantum-safe-ceos1-both Cli <<'EOF'
enable
show running-config section management ssh
show management ssh vrf MGMT
show management ssh
EOF
```

Expect `key-exchange mlkem768x25519-sha256`, MGMT enabled, default VRF disabled.

### Live PQC KEX

From the **test-runner** probe client on the mgmt network:

```bash
docker exec arista-quantum-safe-test-runner sh -c \
  'ssh -vvv \
     -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
     -o PubkeyAuthentication=no -o PreferredAuthentications=keyboard-interactive \
     -o KexAlgorithms=mlkem768x25519-sha256 \
     admin@172.20.127.11 "show hostname | json" 2>&1 | grep "kex: algorithm"'
```

Expected: `kex: algorithm: mlkem768x25519-sha256`

Automated: `make test-ssh` → `[live] SSH (IPv4|IPv6, mlkem768x25519-sha256)`.

See [SSH tests](../tests/ssh.md).

<- [Services overview](index.md)
