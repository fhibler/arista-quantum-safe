# Setup

## Prerequisites

| Item | Required | Notes |
|------|----------|-------|
| Docker + Containerlab 0.78.0 | Yes | `containerlab version` |
| cEOS-lab `ceos:4.36.1F` | Yes | Match host arch (amd64 / arm64) |
| ~10 GB RAM | Yes | Three cEOS containers are memory-heavy |
| Arista portal token | No | For `make download-ceos` only |
| Mgmt subnet | Default OK | Override with `MGMT_SUBNET=` if `.127.0/24` overlaps your host |

## cEOS image

### Option A — portal download (Arista customers)

Requires an [Arista portal token](https://www.arista.com/en/users/profile) with an active maintenance contract:

```bash
cp .env.example .env          # add ARISTA_TOKEN
make download-ceos-help
make download-ceos            # selects cEOS64 or cEOSarm for host arch
make check-ceos-image
```

Downloaded tarballs land in `download/` (gitignored).

### Option B — manual import

Import a cEOS-lab tarball you obtained from Arista:

```bash
docker import /path/to/cEOS64-lab-4.36.1F.tar.xz ceos:4.36.1F
make check-ceos-image
```

Override the expected tag with `CEOS_IMAGE=ceos:4.36.1F make deploy`.

## Deploy workflow

```bash
make gen-topo          # render configs + PKI + topology YAML
make deploy            # build images, deploy KME staging, full topo
make test-lab          # all live checks
```

`make deploy` runs:

1. `make gen-topo` — templates → `lab/.gen/`, validate contract
2. `make build-radius`, `build-syslog`, `build-kme` — Docker images ([PQC overview](pqc-overview.md#openssl-build-requirement-lab-containers) — OpenSSL 3.5 built from source)
3. `make check-ceos-image` — verify local `ceos:4.36.1F`
4. Staged KME deploy + key-pool wait
5. `containerlab deploy -t lab/.gen.quantum-safe.clab.yml`

First cEOS boot can take **5–10 minutes** per node on arm64.

## Makefile variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `CEOS_IMAGE` | `ceos:4.36.1F` | cEOS Docker image tag |
| `CLAB_PREFIX` | `arista` | Container name prefix |
| `CLAB_NAME` | `quantum-safe` | Containerlab lab name |
| `MGMT_SUBNET` | `172.20.127.0/24` | Management network CIDR |
| `QUADRA_SWIX` | (unset) | Path to QuaDRA `.swix` when not in `download/quadra/` |
| `VERBOSE` | (unset) | `VERBOSE=1 make test-pqc` echoes commands |

## Useful targets

| Target | Description |
|--------|-------------|
| `make destroy` | Tear down Containerlab lab |
| `make redeploy` | `destroy` then `deploy` |
| `make clean` | Full reset (lab, images, `.gen/`, downloads) |
| `make inspect` | Node status |
| `make test` | Offline pytest (no deployed lab) |
| `make test-pqc` | PQC management-plane checks only |
| `make ssh-ceos1-both` | Open EOS CLI on a switch |

## Devcontainer

A Docker-in-Docker devcontainer is provided under `.devcontainer/` for a reproducible Containerlab environment. Rebuild after pulling changes.

## Troubleshooting

| Symptom | Action |
|---------|--------|
| `check-ceos-image` fails | Import or download cEOS; verify `docker image inspect ceos:4.36.1F` |
| Deploy stuck at cEOS post-deploy | Wait for EOS POST; check `docker logs <ceos-container>` |
| RadSec / PQC test failures | Confirm radius container healthy; run `make test-pqc VERBOSE=1` |
| Syslog connection cap | Collector defaults to 10 TLS sessions; see [Syslog](services/syslog.md) in Services |
| Host ping failures | Verify data-plane routes in rendered `lab/.gen/ceos*.cfg` |

Reset everything: `make clean` then redeploy from scratch.
