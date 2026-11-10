# Quantum Safe Lab

Containerlab lab demonstrating **post-quantum cryptography (PQC)** on Arista EOS: PQC-hybrid management-plane TLS and SSH (RadSec, eAPI, gNMI, gNPSI, syslog, SSH), **dynamic MACsec** on an inter-switch link, and supporting services (FreeRADIUS, syslog-ng) built with OpenSSL 3.5.

**Tested EOS version: 4.37.0F.** The guides describe this lab version; release comparisons are in the [Changelog](https://fhibler.github.io/arista-quantum-safe/changelog/).

Three EOS switches (`ceos1-both`, `ceos2-pqc`, `ceos3-qkd`) form a small routed topology with Alpine Linux hosts on data segments and a shared management network (`172.20.127.0/24` by default).

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

Automated checks (`make test-lab`) validate configuration and live handshakes on a deployed topology. On EOS **4.37.0F**, syslog and gNPSI TLS/reflection/Subscribe negotiate hybrid PQC. Remaining service limitations and policy gaps are recorded in the [test results](https://fhibler.github.io/arista-quantum-safe/tests/#result-summary).

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| **Linux host** with Docker | amd64 or arm64; ~10 GB RAM for three EOS nodes |
| **Containerlab** 0.78.0+ | `make containerlab-check`; devcontainer installs latest at image build |
| **cEOS-lab image** | Tagged `ceos:4.37.0F` matching your host architecture - **required before deploy** |
| **Arista portal token** | **Optional** - only for `make ceos-image-download` ([create token](https://www.arista.com/en/users/profile); active maintenance contract required) |
| **Python 3.11+** | For offline tests (`make test-offline`) and lab check scripts |

### cEOS-lab image

Obtain cEOS-lab from the [Arista software portal](https://www.arista.com/en/support/software-download) or import a tarball you already have:

```bash
# Optional: auto-download (requires ARISTA_TOKEN in .env)
cp .env.example .env    # add ARISTA_TOKEN
make ceos-image-download
make ceos-image-check

# Or manual import
docker import download/cEOS64-lab-4.37.0F.tar.xz ceos:4.37.0F
make ceos-image-check
```

On arm64, use the downloaded filename (e.g. `cEOSarm-lab-4.37.0F.tar.xz`) but tag as `ceos:4.37.0F`.

## Quick start

```bash
# Generate topology, PKI, and configs
make containerlab-gentopo

# Verify prerequisites
make containerlab-check
make ceos-image-check

# Build service images and deploy (KME nodes first, then full topo)
make containerlab-deploy

# Run all live acceptance checks
make test-lab

# On a bare host without PQC curl on the OS (Docker + deployed lab only):
make test-lab-runner
```

Individual test targets: `make test-radsec`, `make test-eapi`, `make test-ssh`, `make test-openconfig`, `make test-syslog`, `make test-kme`, `make test-macsec-dot1x`, `make test-macsec-qkd`, `make test-hosts`. Use `VERBOSE=1` to echo commands. Manual PQC probes: `make test-runner-shell`.

Workspace shortcuts: `make deploy`, `make redeploy`, `make destroy`, and `make inspect` alias the corresponding `containerlab-*` targets.

Offline validation (no deployed lab required):

```bash
pip install -r requirements-dev.txt
make test-offline
```

## Topology overview

| Node | Role |
|------|------|
| ceos1-both, ceos2-pqc, ceos3-qkd | EOS switches - MGMT VRF, RadSec, remote syslog (TLS), dynamic MACsec on eth1 (ceos1 <-> ceos2) |
| host1, host2, host3 | Alpine hosts on routed data segments |
| radius | FreeRADIUS (RadSec + EAP-TLS for 802.1X) |
| syslog | syslog-ng collector (TLS 6514, OpenSSL 3.5 PQC-hybrid) |
| test-runner | PQC probe client (OpenSSL 3.5 + curl) for live checks and manual debug |

Container names follow `{prefix}-quantum-safe-{node}` (default prefix `arista` -> `arista-quantum-safe-ceos1-both`).

## Proprietary dependencies

This repository ships **lab tooling and configuration templates only**. It does **not** redistribute:

- Arista **cEOS-lab** container images
- Arista **QuaDRA** or other EOS extension packages

You must obtain those separately under your Arista license or support agreement.

- **cEOS-lab** is available after registration from [arista.com](https://www.arista.com) (software download). If you are a customer, use the website token under **arista.com -> My Profile**.
- **QuaDRA** must be obtained via your **Arista account team**.

## Author

**Florian Hibler** - florian@arista.com

## License

See [LICENSE](LICENSE) (lab tooling). Arista EOS remains a proprietary Arista product.
