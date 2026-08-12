# Quantum Safe Lab

Containerlab lab demonstrating **post-quantum cryptography (PQC)** on Arista cEOS: PQC-hybrid management-plane TLS with **no classical fallback** on most services (RadSec, eAPI, gNMI, RESTCONF, SSH), **dynamic MACsec** on an inter-switch link, and supporting services (FreeRADIUS, syslog-ng) built with OpenSSL 3.5.

Three cEOS switches (`ceos1-both`, `ceos2-pqc`, `ceos3-qkd`) form a small routed topology with Alpine Linux hosts on data segments and a shared management network (`172.20.127.0/24` by default).

<!-- site-config:begin -->
**Documentation:** [https://fhibler.github.io/arista-quantum-safe/](https://fhibler.github.io/arista-quantum-safe/) (GitHub Pages)

## Documentation map

| Topic | Location |
|-------|----------|
| Setup, Makefile variables, troubleshooting | [Setup guide](https://fhibler.github.io/arista-quantum-safe/setup/) |
| Per-service PQC configuration | [Services](https://fhibler.github.io/arista-quantum-safe/services/) |
| Live test suite (`make test-lab`) | [Tests](https://fhibler.github.io/arista-quantum-safe/tests/) |
<!-- site-config:end -->
## Purpose

The lab shows how to configure and verify **PQC-hybrid key establishment** (`X25519MLKEM768` for TLS 1.3, `mlkem768x25519-sha256` for SSH) across common EOS management interfaces, plus **802.1X EAP-TLS + MKA dynamic MACsec** protected by the same hybrid TLS groups on the RADIUS path.

Automated checks (`make test-lab`) validate configuration and live handshakes on a deployed topology.

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| **Linux host** with Docker | amd64 or arm64; ~10 GB RAM for three cEOS nodes |
| **Containerlab** 0.78.0+ | Installed on the host or via the repo devcontainer |
| **cEOS-lab image** | Tagged `ceos:4.36.1F` matching your host architecture — **required before deploy** |
| **Arista portal token** | **Optional** — only for `make download-ceos` ([create token](https://www.arista.com/en/users/profile); active maintenance contract required) |
| **Python 3.11+** | For offline tests (`make test`) and lab check scripts |

### cEOS image

Obtain cEOS-lab from the [Arista software portal](https://www.arista.com/en/support/software-download) or import a tarball you already have:

```bash
# Optional: auto-download (requires ARISTA_TOKEN in .env)
cp .env.example .env    # add ARISTA_TOKEN
make download-ceos
make check-ceos-image

# Or manual import
docker import download/cEOS64-lab-4.36.1F.tar.xz ceos:4.36.1F
make check-ceos-image
```

On arm64, use the downloaded filename (e.g. `cEOSarm-lab-4.36.1F-EFT1.tar.xz`) but tag as `ceos:4.36.1F`.

## Quick start

```bash
# Generate topology, PKI, and configs
make gen-topo

# Build service images and deploy (KME nodes first, then full topo)
make deploy

# Run all live acceptance checks
make test-lab
```

Individual test targets: `make test-radius`, `make test-pqc`, `make test-syslog`, `make test-macsec`, `make test-hosts`. Use `VERBOSE=1` to echo commands.

Offline validation (no cEOS required):

```bash
pip install -r requirements-dev.txt
make test
```

## Topology overview

| Node | Role |
|------|------|
| ceos1-both, ceos2-pqc, ceos3-qkd | cEOS switches — MGMT VRF, RadSec, remote syslog (TLS), dynamic MACsec on eth1 (ceos1 ↔ ceos2) |
| host1, host2, host3 | Alpine hosts on routed data segments |
| radius | FreeRADIUS (RadSec + EAP-TLS for 802.1X) |
| syslog | syslog-ng collector (TLS 6514, OpenSSL 3.5 PQC-hybrid) |

Container names follow `{prefix}-quantum-safe-{node}` (default prefix `arista` → `arista-quantum-safe-ceos1-both`).

## Proprietary dependencies

This repository ships **lab tooling and configuration templates only**. It does **not** redistribute:

- Arista **cEOS-lab** container images
- Arista **QuaDRA** or other EOS extension packages

You must obtain those separately under your Arista license or support agreement.

## License

See [LICENSE](LICENSE) (lab tooling). cEOS and Arista EOS remain proprietary Arista products.
