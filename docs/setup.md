# Setup

## Prerequisites

| Item | Required | Notes |
|------|----------|-------|
| Docker + Containerlab 0.78.0+ | Yes | `make containerlab-check` (devcontainer installs latest at image build) |
| cEOS-lab `ceos:4.37.0F` | Yes | Match host arch (amd64 / arm64) |
| ~10 GB RAM | Yes | |
| Arista portal token | No | For `make ceos-image-download` only |
| Mgmt subnet | Default OK | Override with `MGMT_SUBNET=` if `.127.0/24` overlaps your host |

## cEOS-lab image

### Option A - automated download from arista.com

Requires an [Arista portal token](https://www.arista.com/en/users/profile) with an active maintenance contract:

```bash
cp .env.example .env          # optional overrides (CEOS_IMAGE, MGMT_SUBNET, ARISTA_TOKEN, …)
make ceos-image-help
make ceos-image-download  # selects cEOS64 or cEOSarm for host arch
make ceos-image-check
```

Downloaded tarballs land in `download/` (gitignored).

### Option B - manual import

Should you not be able to obtain a portal token, cEOS-lab is freely available after registration on [arista.com](https://www.arista.com). Download the tarball for your architecture from the [Arista software portal](https://www.arista.com/en/support/software-download), then import it locally:

```bash
docker import /path/to/cEOS64-lab-4.37.0F.tar.xz ceos:4.37.0F
make ceos-image-check
```

The default is `ceos:4.37.0F`. To deploy another imported image, set `CEOS_IMAGE` when invoking `make containerlab-deploy`.

## Deploy workflow

```bash
make containerlab-gentopo           # render configs + PKI + topology YAML
make containerlab-deploy            # build images, deploy KME staging, full topo
make containerlab-deploy VERBOSE=1  # same, with plain Docker build logs and debug containerlab output
make test-lab          # all live checks
```

`make containerlab-deploy` runs:

1. `make containerlab-gentopo` - templates -> `lab/.gen/`, validate contract
2. `make containerlab-check` - Containerlab installed and new enough
3. `make images-build` - `docker buildx bake` of radius, syslog, kme, and test-runner ([Tool chain](misc/toolchain.md) - OpenSSL **3.5.0** minimum for PQC-safe TLS; Alpine **3.24** is pinned; apk OpenSSL **3.5.x** patch releases float)
4. `make ceos-image-check` - verify local `ceos:4.37.0F`
5. `make images-kme-deploy` - staged KME deploy
6. Key-pool wait (`images-kme-pool-wait`)
7. `containerlab deploy -t lab/.gen.quantum-safe.clab.yml`

The EOS **4.37.0F** verification used apk OpenSSL **3.5.9** in peer/probe containers and bundled OpenSSL **3.5.5** in EOS. These are separate TLS stacks; a version number alone does not establish each service’s live KEX.

First EOS boot can take **5–10 minutes** per node on arm64.

!!! note "Staged deploy"
    `images-kme-deploy` and `images-kme-pool-wait` are for manual debugging only. Do **not** run `make images-kme-deploy` and then `make containerlab-deploy` back-to-back - `containerlab-deploy` already calls `images-kme-deploy` internally, and Containerlab rejects a second `--node-filter` deploy while KME nodes are already running. Use `make containerlab-deploy` or `make containerlab-redeploy` for a full bring-up.

## Makefile reference

Run `make help` for the supported targets, grouped in source order. Workspace shortcuts `deploy`, `redeploy`, `destroy`, and `inspect` alias the corresponding `containerlab-*` targets and accept the same variables.

### General

| Target | Description |
|--------|-------------|
| `make help` | Show available targets by category |

### Containerlab

| Target | Description |
|--------|-------------|
| `make containerlab-check` | Verify Containerlab is installed and >= `CLAB_MIN_VERSION` |
| `make containerlab-gentopo` | Render `lab/.gen/`, PKI, and topology YAML; validate contract |
| `make containerlab-validate` | Contract-check generated topology |
| `make containerlab-deploy` | Generate topology, build and verify all images, stage KMEs, wait for keys, deploy the lab |
| `make containerlab-destroy` | Tear down the Containerlab lab |
| `make containerlab-redeploy` | Generate topology, destroy the lab, then run the full deployment |
| `make containerlab-inspect` | Show node status |

Deployment phases and the generate/destroy/deploy sequence finish in order, including with `make -j`. A failed phase stops the workflow before later phases run.

### cEOS image management

| Target | Description |
|--------|-------------|
| `make ceos-image-check` | Verify the local cEOS image and host architecture; import an available tarball if needed |
| `make ceos-image-import` | Import a cEOS tarball from `CEOS_DOWNLOAD_DIR` |
| `make ceos-image-download` | Download and import cEOS, or import an existing tarball |
| `make ceos-image-help` | Show manual import, download, and token instructions |
| `make ceos-quadra-install` | Install QuaDRA on ceos1-both and ceos3-qkd using `QUADRA_SWIX` or `download/quadra/` |

### Lab images

| Target | Description |
|--------|-------------|
| `make images-build` | Generate and validate configs, build all lab images, then verify them |
| `make images-check` | Verify existing lab images without rebuilding |
| `make images-kme-deploy` | Deploy KME nodes for staged startup (debugging only; see note above) |
| `make images-kme-pool-wait` | Wait for KME key-pool readiness after staging |

`images-build` and `images-check` accept `IMAGE=radius`, `IMAGE=syslog`, `IMAGE=kme`, or `IMAGE=test-runner`. Omit `IMAGE` to select all four service/probe images. Invalid selections fail before generating configs or invoking Docker. A build always verifies its selected images. Building only the test-runner does not require generated lab configs.

```bash
make images-build IMAGE=radius
make images-check IMAGE=radius
make images-build IMAGE=test-runner VERBOSE=1
make images-check
```

`containerlab-deploy` always builds and verifies all four images, regardless of an `IMAGE` setting. Builds use Docker Buildx Bake for the host architecture. Alpine **3.24** is pinned; apk OpenSSL patch releases float. PQC-safe TLS requires OpenSSL **3.5.0** or later; see [Tool chain](misc/toolchain.md).

### Node access

| Target | Description |
|--------|-------------|
| `make ceos-cli NODE=ceos1-both` | Open the selected switch's EOS CLI through Docker |
| `make test-runner-shell` | Open an interactive shell on the deployed test-runner |

`ceos-cli` requires `NODE=ceos1-both`, `NODE=ceos2-pqc`, or `NODE=ceos3-qkd`. Missing or invalid node selections fail before Docker runs.

### Tests

| Target | Description |
|--------|-------------|
| `make test-offline` | Run offline pytest (no deployed lab) |
| `make test-lab` | Run all standard live lab checks |
| `make test-lab-runner` | Run the same checks through the Docker harness |
| `make test-ssh` / `test-eapi` / `test-radsec` / `test-syslog` / `test-openconfig` / `test-kme` / `test-macsec-dot1x` / `test-macsec-qkd` / `test-hosts` | Run one live suite |
| `make test-macsec-dot1x-reauth` | Verify MACsec with periodic reauthentication (~75 s) |

Add `VERBOSE=1` to a live test target to echo commands and full output. `test-offline` uses the repository's default pytest selection, which excludes Containerlab integration tests; run `python3 -m pytest -o addopts=` to include them when Containerlab is available.

### Documentation

| Target | Description |
|--------|-------------|
| `make docs-config-sync` | Sync README and MkDocs site settings from `site.yaml` |

### Workspace

| Target | Description |
|--------|-------------|
| `make deploy` | Alias for `containerlab-deploy` |
| `make redeploy` | Alias for `containerlab-redeploy` |
| `make destroy` | Alias for `containerlab-destroy` |
| `make inspect` | Alias for `containerlab-inspect` |
| `make clean` | Tear down the lab and remove generated files, logs, `tmp/`, caches, and project Docker images; keep `download/`, `.env`, and BuildKit cache |
| `make reset` | Run `clean`, restore HEAD, remove untracked/ignored files, and prune BuildKit cache; discard local changes |

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
| `CEOS_IMAGE` | `ceos:4.37.0F` | cEOS-lab Docker image tag |
| `CEOS_DOWNLOAD_DIR` | `download` | Directory for cEOS tarballs |
| `CLAB_PREFIX` | `arista` | Container name prefix fixed by the topology contract |
| `CLAB_NAME` | `quantum-safe` | Lab name fixed by the topology contract |
| `MGMT_SUBNET` | `172.20.127.0/24` | Management network IPv4 CIDR |
| `MGMT_IPV6_SUBNET` | `2001:db8:127::/64` | Management network IPv6 CIDR |
| `CLAB_MIN_VERSION` | `0.78.0` | Minimum Containerlab version enforced by `make containerlab-check` |
| `IMAGE` | (unset: all) | Select one service/probe image for `images-build` or `images-check` |
| `NODE` | (unset: required) | Switch name for `ceos-cli` |
| `QUADRA_SWIX` | (unset) | Path to QuaDRA `.swix` when not in `download/quadra/` |
| `ALPINE_VERSION` | `3.24` | Alpine pin for lab image bake (`docker/base` and test-runner fetch/Go stages) |
| `VERBOSE` | (unset) | `make containerlab-deploy VERBOSE=1` - plain Docker build logs (`--progress=plain`), containerlab `-d`, verbose KME wait; `make test-eapi VERBOSE=1` echoes live-test commands |

Copy `.env.example` → `.env` to set the configurable defaults persistently. The Makefile `-include`s `.env` for every target. Command-line assignments override `.env`, which overrides shell environment values. `CLAB_PREFIX` and `CLAB_NAME` are fixed Makefile values and are not configurable through `.env`; the topology renderer and validation contract also fix these identities.

## Devcontainer

A Docker-in-Docker devcontainer is provided under `.devcontainer/` for a reproducible Containerlab environment. Rebuild after pulling changes.

## Troubleshooting

| Symptom | Action |
|---------|--------|
| Deploy fails after manual `images-kme-deploy` | Run `make containerlab-deploy` or `make containerlab-redeploy` instead of `images-kme-deploy` followed by `containerlab-deploy` |
| Direct `containerlab` command: `Authentication required: Repository not found` | Check that `lab/.gen.quantum-safe.clab.yml` exists; run `make containerlab-gentopo`. `make containerlab-destroy` and `make containerlab-redeploy` generate a missing topology automatically. |
| `ceos-image-check` fails | Import or download cEOS-lab; verify `docker image inspect ceos:4.37.0F` |
| `containerlab-check` fails (not installed) | Install Containerlab 0.78.0+ or rebuild the devcontainer |
| `containerlab-check` fails (too old) | Upgrade to >= 0.78.0 (`containerlab version upgrade`, or rebuild the devcontainer) |
| Deploy stuck at EOS post-deploy | Wait for EOS POST; check `docker logs <ceos-container>` |
| RadSec / PQC test failures | Confirm radius container healthy; run `make test-radsec VERBOSE=1`; on hosts without PQC curl use `make test-lab-runner` |
| Syslog connection cap | The lab collector allows 32 TLS sessions; leave headroom for persistent switch sessions, probes, and health checks. See [Syslog](services/syslog.md). |
| Host ping failures | Verify data-plane routes in rendered `lab/.gen/ceos*.cfg` |

Reset lab artifacts while keeping cEOS tarballs, `.env`, and the Docker BuildKit cache: `make clean`, then redeploy from scratch.

To discard **all** local changes and gitignored files (including `download/`, `.env`, and the BuildKit cache), use `make reset` instead.
