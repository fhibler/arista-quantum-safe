# Setup

## Prerequisites

| Item | Required | Notes |
|------|----------|-------|
| Docker + Containerlab 0.78.0+ | Yes | `make check-containerlab` (devcontainer installs latest at image build) |
| cEOS-lab `ceos:4.36.2F` | Yes | Match host arch (amd64 / arm64) |
| ~10 GB RAM | Yes | |
| Arista portal token | No | For `make download-ceos` only |
| Mgmt subnet | Default OK | Override with `MGMT_SUBNET=` if `.127.0/24` overlaps your host |

## cEOS-lab image

### Option A — automated download from arista.com

Requires an [Arista portal token](https://www.arista.com/en/users/profile) with an active maintenance contract:

```bash
cp .env.example .env          # optional overrides (CEOS_IMAGE, MGMT_SUBNET, ARISTA_TOKEN, …)
make download-ceos-help
make download-ceos            # selects cEOS64 or cEOSarm for host arch
make check-ceos-image
```

Downloaded tarballs land in `download/` (gitignored).

### Option B — manual import

Should you not be able to obtain a portal token, cEOS-lab is freely available after registration on [arista.com](https://www.arista.com). Download the tarball for your architecture from the [Arista software portal](https://www.arista.com/en/support/software-download), then import it locally:

```bash
docker import /path/to/cEOS64-lab-4.36.2F.tar.xz ceos:4.36.2F
make check-ceos-image
```

Override the expected tag with `CEOS_IMAGE=ceos:4.36.2F make deploy`.

## Deploy workflow

```bash
make gen-topo          # render configs + PKI + topology YAML
make deploy            # build images, deploy KME staging, full topo
make deploy VERBOSE=1  # same, with plain Docker build logs and debug containerlab output
make test-lab          # all live checks
```

`make deploy` runs:

1. `make gen-topo` — templates -> `lab/.gen/`, validate contract
2. `make check-containerlab` — Containerlab installed and new enough
3. `make build-lab-images` — `docker buildx bake` of radius, syslog, kme, and test-runner ([Tool chain](misc/toolchain.md) — OpenSSL **3.5.0** minimum for PQC-safe TLS; lab pin is Alpine 3.24 apk **3.5.7**)
4. `make check-ceos-image` — verify local `ceos:4.36.2F`
5. `make deploy-kme` — staged KME deploy
6. Key-pool wait (`wait-kme-pool`)
7. `containerlab deploy -t lab/.gen.quantum-safe.clab.yml`

First EOS boot can take **5–10 minutes** per node on arm64.

!!! note "Staged deploy"
    `deploy-kme` and `wait-kme-pool` are for manual debugging only. Do **not** run `make deploy-kme` and then `make deploy` back-to-back — `deploy` already calls `deploy-kme` internally, and Containerlab rejects a second `--node-filter` deploy while KME nodes are already running. Use `make deploy` or `make redeploy` for a full bring-up.

## Makefile reference

Run `make help` for the authoritative target list in your clone.

### Topology and offline validation

| Target | Description |
|--------|-------------|
| `make help` | List available targets |
| `make gen-topo` | Render `lab/.gen/`, PKI, and topology YAML; validate contract |
| `make validate-topo` | Contract-check generated topology |
| `make test` | Offline pytest (no deployed lab) |

### cEOS-lab and preflight

| Target | Description |
|--------|-------------|
| `make check-containerlab` | Verify Containerlab is installed and >= `CLAB_MIN_VERSION` |
| `make check-ceos-image` | Verify cEOS-lab image exists and matches host arch |
| `make import-ceos-help` / `make download-ceos-help` | Print import or download instructions |
| `make import-ceos` / `make download-ceos` | Import tarball from `download/` or download via Arista API |

### Images and deploy

| Target | Description |
|--------|-------------|
| `make build-lab-images` | `docker buildx bake` radius, syslog, kme, and test-runner (Alpine 3.24 apk OpenSSL **3.5.7**; PQC-safe minimum is OpenSSL **3.5.0**) |
| `make build-radius` / `build-syslog` / `build-kme` / `build-test-runner` | Build one lab image (includes image smoke tests) |
| `make deploy` | Full lab bring-up (gen-topo, builds, KME staging, full topo) |
| `make deploy-kme` / `make wait-kme-pool` | Staged KME deploy and key-pool wait (debugging only; see note above) |
| `make destroy` | Tear down Containerlab lab |
| `make redeploy` | `gen-topo`, then `destroy`, then `deploy` |
| `make clean` | Tear down lab, remove build artifacts and Docker images (including the local `CEOS_IMAGE` tag); **keeps** `download/`, `.env`, and the Docker BuildKit cache |
| `make reset` | `clean`, then `git reset --hard HEAD`, `git clean -fdx`, and `docker buildx prune` (discards local edits, gitignored files, and build cache) |
| `make inspect` | Node status |

### Live tests and shells

| Target | Description |
|--------|-------------|
| `make test-lab` | All live lab checks |
| `make test-lab-runner` | Same checks from mgmt-network harness (Docker only) |
| `make test-radsec` / `test-kme` / `test-eapi` / `test-ssh` / `test-openconfig` / `test-syslog` / `test-macsec-dot1x` / `test-macsec-qkd` / `test-hosts` | Individual live check sections |
| `make test-macsec-dot1x-reauth` | MACsec plus ~75 s 802.1X reauth wait |
| `make install-quadra` | Install QuaDRA swix on ceos1-both and ceos3-qkd (when present) |
| `make ssh-ceos1-both` / `ssh-ceos2-pqc` / `ssh-ceos3-qkd` | EOS CLI shells |
| `make shell-test-runner` | Interactive PQC probe shell on `test-runner` |

Add `VERBOSE=1` to any live test target to echo commands and full output.

### Building this documentation site

Build locally with MkDocs:

```bash
pip install -r docs/requirements.txt
mkdocs build --strict
```

GitHub Pages builds from [`.github/workflows/pages.yml`](https://github.com/fhibler/arista-quantum-safe/blob/main/.github/workflows/pages.yml) on each push to `main`.

## Makefile variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `CEOS_IMAGE` | `ceos:4.36.2F` | cEOS-lab Docker image tag |
| `CLAB_PREFIX` | `arista` | Container name prefix |
| `CLAB_NAME` | `quantum-safe` | Containerlab lab name |
| `MGMT_SUBNET` | `172.20.127.0/24` | Management network IPv4 CIDR |
| `MGMT_IPV6_SUBNET` | `2001:db8:127::/64` | Management network IPv6 CIDR |
| `CLAB_MIN_VERSION` | `0.78.0` | Minimum Containerlab version enforced by `make check-containerlab` |
| `QUADRA_SWIX` | (unset) | Path to QuaDRA `.swix` when not in `download/quadra/` |
| `ALPINE_VERSION` | `3.24` | Alpine pin for lab image bake (`docker/base` and test-runner fetch/Go stages) |
| `VERBOSE` | (unset) | `VERBOSE=1 make deploy` — plain Docker build logs (`--progress=plain`), containerlab `-d`, verbose KME wait; `VERBOSE=1 make test-eapi` echoes live-test commands |

Copy `.env.example` → `.env` to set any of the above persistently. The Makefile `-include`s `.env` for every target (command-line assignments override).

## Devcontainer

A Docker-in-Docker devcontainer is provided under `.devcontainer/` for a reproducible Containerlab environment. Rebuild after pulling changes.

## Troubleshooting

| Symptom | Action |
|---------|--------|
| Deploy fails after manual `deploy-kme` | Run `make deploy` or `make redeploy` instead of `deploy-kme` followed by `deploy` |
| `destroy` / `redeploy`: `Authentication required: Repository not found` | Generated topology missing; run `make gen-topo` first (or use `make redeploy`, which now runs it automatically) |
| `check-ceos-image` fails | Import or download cEOS-lab; verify `docker image inspect ceos:4.36.2F` |
| `check-containerlab` fails (not installed) | Install Containerlab 0.78.0+ or rebuild the devcontainer |
| `check-containerlab` fails (too old) | Upgrade to >= 0.78.0 (`containerlab version upgrade`, or rebuild the devcontainer) |
| Deploy stuck at EOS post-deploy | Wait for EOS POST; check `docker logs <ceos-container>` |
| RadSec / PQC test failures | Confirm radius container healthy; run `make test-radsec VERBOSE=1`; on hosts without PQC curl use `make test-lab-runner` |
| Syslog connection cap | Collector defaults to 10 TLS sessions; see [Syslog](services/syslog.md) in Services |
| Host ping failures | Verify data-plane routes in rendered `lab/.gen/ceos*.cfg` |

Reset lab artifacts while keeping cEOS tarballs, `.env`, and the Docker BuildKit cache: `make clean`, then redeploy from scratch.

To discard **all** local changes and gitignored files (including `download/`, `.env`, and the BuildKit cache), use `make reset` instead.
