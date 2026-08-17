# Quantum Safe lab — Containerlab lifecycle

SHELL := /bin/bash
.DEFAULT_GOAL := help

CLAB_VERSION  ?= 0.78.2
CEOS_IMAGE ?= ceos:4.36.2F
CEOS_VERSION ?= $(shell echo "$(CEOS_IMAGE)" | cut -d: -f2)
CEOS_DOCKER_NAME ?= $(shell echo "$(CEOS_IMAGE)" | cut -d: -f1)
CEOS_DOWNLOAD_DIR ?= download
QUADRA_SWIX ?=
CLAB_TOPO_SRC := lab/quantum-safe.clab.yml
CLAB_TOPO_ANN := lab/quantum-safe.clab.yml.annotations.json
CLAB_TOPO_GEN := lab/.gen.quantum-safe.clab.yml
CLAB_PREFIX   := arista
CLAB_NAME     := quantum-safe
CLAB_MGMT_NETWORK := quantum-safe-mgmt
MGMT_SUBNET   ?= 172.20.127.0/24
GEN_CONFIGS   := lab/.gen/clients.conf lab/.gen/clients-radsec.conf lab/.gen/ceos1-both.cfg lab/.gen/ceos2-pqc.cfg lab/.gen/ceos3-qkd.cfg lab/.gen/kme-lab.conf $(addprefix lab/.gen/pki/,ca.pem server.pem radsec-ca.pem syslog-server.pem syslog-server.key ceos1-both-client.pem ceos1-both-client.key ceos1-both-eapi.pem ceos1-both-eapi.key ceos1-both-gnmi.pem ceos1-both-gnmi.key ceos2-pqc-client.pem ceos2-pqc-client.key ceos2-pqc-eapi.pem ceos2-pqc-eapi.key ceos2-pqc-gnmi.pem ceos2-pqc-gnmi.key ceos3-qkd-client.pem ceos3-qkd-client.key ceos3-qkd-eapi.pem ceos3-qkd-eapi.key ceos3-qkd-gnmi.pem ceos3-qkd-gnmi.key) $(addprefix lab/.gen/kme-pki/,ca.crt.pem kme-a.crt.pem kme-a.key.pem kme-b.crt.pem kme-b.key.pem sae.crt.pem sae.key.pem sae-b.crt.pem sae-b.key.pem kme-sae-bundle.pem kme-sae-b-bundle.pem)
RADIUS_IMAGE  := quantum-safe-radius:latest
RADIUS_DOCKERFILE := docker/radius/Dockerfile
SYSLOG_IMAGE  := quantum-safe-syslog:latest
SYSLOG_DOCKERFILE := docker/syslog/Dockerfile
KME_IMAGE     := quantum-safe-kme:latest
KME_DOCKERFILE := docker/kme/Dockerfile
TEST_RUNNER_IMAGE := quantum-safe-test-runner:latest
TEST_RUNNER_DOCKERFILE := docker/test-runner/Dockerfile
HOST_ARCH     := $(shell uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')
# Do not inherit VERBOSE from the environment; use make test-lab VERBOSE=1 explicitly.
VERBOSE       :=
PYTHON        := $(shell [ -x .venv/bin/python3 ] && echo .venv/bin/python3 || echo python3)
MGMT_IP_RADIUS = $(shell $(PYTHON) -c "from lab.topology_contract import mgmt_ips_for_subnet; print(mgmt_ips_for_subnet('$(MGMT_SUBNET)')['radius'])")
MGMT_IP_KME_A = $(shell $(PYTHON) -c "from lab.topology_contract import mgmt_ips_for_subnet; print(mgmt_ips_for_subnet('$(MGMT_SUBNET)')['kme-a'])")
MGMT_IP_KME_B = $(shell $(PYTHON) -c "from lab.topology_contract import mgmt_ips_for_subnet; print(mgmt_ips_for_subnet('$(MGMT_SUBNET)')['kme-b'])")
KME_SAE_ID = $(shell $(PYTHON) -c "from lab.topology_contract import KME_SAE_ID; print(KME_SAE_ID)")

LAB_TEST = $(PYTHON) -m lab.test_lab --clab-name '$(CLAB_NAME)' --mgmt-subnet '$(MGMT_SUBNET)' \
	--clab-topo-gen '$(CLAB_TOPO_GEN)' $(if $(filter 1,$(VERBOSE)),--verbose,)

.PHONY: help gen-topo validate-topo sync-devcontainer sync-site-config docs-build export-public publish-public test check-ceos-image import-ceos import-ceos-help \
        download-ceos download-ceos-help build-radius build-syslog build-kme deploy-kme wait-kme-pool deploy destroy redeploy \
        clean inspect graph ssh-ceos1-both ssh-ceos2-pqc ssh-ceos3-qkd shell-test-runner install-quadra test-lab test-lab-runner test-radius test-syslog test-kme test-pqc test-macsec test-macsec-reauth test-qkd test-hosts

help: ## Show available targets
	@grep -E '^[a-zA-Z0-9_-]+:.*##' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  %-20s %s\n", $$1, $$2}'

$(CLAB_TOPO_GEN) $(GEN_CONFIGS): $(CLAB_TOPO_SRC) $(CLAB_TOPO_ANN) configs/ceos/ceos1-both.cfg.in configs/ceos/ceos2-pqc.cfg.in configs/ceos/ceos3-qkd.cfg.in configs/ceos/quadra-daemon-master.cfg.in configs/ceos/quadra-daemon-slave.cfg.in configs/ceos/quadra-macsec-master.cfg.in configs/ceos/quadra-macsec-slave.cfg.in configs/radius/raddb/clients.conf.in configs/radius/raddb/clients-radsec.conf.in
	@$(PYTHON) -m lab.render_topo --ceos-image '$(CEOS_IMAGE)' --mgmt-subnet '$(MGMT_SUBNET)'

gen-topo: ## Generate topology YAML with CEOS_IMAGE / MGMT_SUBNET overrides
	@env $(if $(QUADRA_SWIX),QUADRA_SWIX='$(QUADRA_SWIX)',) \
		$(PYTHON) -m lab.render_topo --ceos-image '$(CEOS_IMAGE)' --mgmt-subnet '$(MGMT_SUBNET)'
	@$(MAKE) --no-print-directory validate-topo
	@$(MAKE) --no-print-directory sync-devcontainer

sync-devcontainer: ## Sync CLAB_VERSION from Makefile into .devcontainer/devcontainer.json
	@$(PYTHON) -m lab.sync_devcontainer --clab-version '$(CLAB_VERSION)'

sync-site-config: ## Sync README.md and mkdocs.yml site blocks from site.yaml
	@$(PYTHON) scripts/site_config.py --sync-readme
	@$(PYTHON) scripts/site_config.py --sync-mkdocs

docs-build: ## Build public docs site (MkDocs strict + export boundary check)
	@$(PYTHON) scripts/site_config.py --check
	mkdocs build --strict
	@$(PYTHON) scripts/check_public_export.py

export-public: ## Filter history and verify public mirror locally (Option B dry-run; internal only)
	@test -f scripts/export_public.py || (echo 'export-public is internal-only (scripts/export_public.py not present)'; exit 1)
	@$(PYTHON) scripts/export_public.py --source-dir '$(CURDIR)' --branch '$$(git branch --show-current)' --dry-run --keep-work-dir

publish-public: ## Filter history and force-push to PUBLIC_GITHUB_URL (Option B; internal only)
	@test -f scripts/export_public.py || (echo 'publish-public is internal-only (scripts/export_public.py not present)'; exit 1)
	@test -n '$(PUBLIC_GITHUB_URL)' || (echo 'Set PUBLIC_GITHUB_URL to the public GitHub remote URL'; exit 1)
	@$(PYTHON) scripts/export_public.py --source-dir '$(CURDIR)' --branch '$$(git branch --show-current)' --push --remote-url '$(PUBLIC_GITHUB_URL)'

validate-topo: $(CLAB_TOPO_GEN) ## Validate generated topology against contract
	@$(PYTHON) -m lab.validate_topo $(CLAB_TOPO_GEN) --ceos-image '$(CEOS_IMAGE)' --mgmt-subnet '$(MGMT_SUBNET)'

test: ## Run offline pytest (scaffold + contract validation)
	$(PYTHON) -m pytest

check-ceos-image: ## Fail if cEOS image missing or architecture mismatches host
	@set -euo pipefail; \
	if ! docker image inspect "$(CEOS_IMAGE)" >/dev/null 2>&1; then \
		echo "cEOS image '$(CEOS_IMAGE)' not found locally."; \
		echo ""; \
		$(MAKE) --no-print-directory import-ceos-help; \
		exit 1; \
	fi; \
	img_arch=$$(docker image inspect "$(CEOS_IMAGE)" -f '{{.Architecture}}'); \
	host_arch=$$(uname -m); \
	case "$$host_arch" in \
		x86_64|amd64) host_arch=amd64 ;; \
		aarch64|arm64) host_arch=arm64 ;; \
	esac; \
	if [ "$$img_arch" != "$$host_arch" ]; then \
		echo "cEOS image architecture mismatch for '$(CEOS_IMAGE)'."; \
		echo "  image: $$img_arch"; \
		echo "  host:  $$host_arch"; \
		echo ""; \
		echo "Re-import the correct tarball for your platform:"; \
		echo "  amd64  → $(CEOS_DOWNLOAD_DIR)/cEOS64-lab-$(CEOS_VERSION).tar.xz"; \
		echo "  arm64  → $(CEOS_DOWNLOAD_DIR)/cEOSarm-lab-$(CEOS_VERSION).tar.xz (EFT suffix OK)"; \
		echo ""; \
		$(MAKE) --no-print-directory import-ceos-help; \
		exit 1; \
	fi; \
	echo "cEOS image '$(CEOS_IMAGE)' present ($$img_arch)"

import-ceos: ## Import cEOS tarball from download/ (no API token)
	@set -euo pipefail; \
	case "$$(uname -m)" in \
		x86_64|amd64)  CEOS_TAR="$(CEOS_DOWNLOAD_DIR)/cEOS64-lab-$(CEOS_VERSION).tar.xz" ;; \
		aarch64|arm64) \
			CEOS_TAR="$(CEOS_DOWNLOAD_DIR)/cEOSarm-lab-$(CEOS_VERSION).tar.xz"; \
			if [ ! -f "$$CEOS_TAR" ]; then \
				CEOS_TAR=$$(compgen -G "$(CEOS_DOWNLOAD_DIR)/cEOSarm-lab-$(CEOS_VERSION)"*.tar.xz 2>/dev/null | head -1 || true); \
			fi ;; \
		*) echo "unsupported architecture: $$(uname -m)"; exit 1 ;; \
	esac; \
	if [ -z "$${CEOS_TAR:-}" ] || [ ! -f "$$CEOS_TAR" ]; then \
		echo "cEOS tarball not found under $(CEOS_DOWNLOAD_DIR)/"; \
		$(MAKE) --no-print-directory import-ceos-help; \
		exit 1; \
	fi; \
	echo "Importing $$CEOS_TAR → $(CEOS_IMAGE)"; \
	docker import "$$CEOS_TAR" "$(CEOS_IMAGE)"; \
	$(MAKE) --no-print-directory check-ceos-image

import-ceos-help: ## Print manual docker import one-liners (amd64 / arm64)
	@echo "# Manual import (no API token required):"
	@echo ""
	@echo "# amd64:"
	@echo "docker import $(CEOS_DOWNLOAD_DIR)/cEOS64-lab-$(CEOS_VERSION).tar.xz $(CEOS_IMAGE)"
	@echo ""
	@echo "# aarch64:"
	@echo "docker import $(CEOS_DOWNLOAD_DIR)/cEOSarm-lab-$(CEOS_VERSION).tar.xz $(CEOS_IMAGE)"
	@echo ""
	@echo "# Or use the arch-aware helper:"
	@echo "make import-ceos"
	@echo ""
	@echo "# Optional auto-download (requires ARISTA_TOKEN — see make download-ceos-help):"
	@echo "make download-ceos"

download-ceos-help: ## Print Arista token setup and ardl usage
	@echo "# 1. Get Arista portal token: https://www.arista.com/en/users/profile"
	@echo "# 2. export ARISTA_TOKEN=<token>   # or copy .env.example → .env"
	@echo "# 3. make download-ceos            # arch-aware cEOS64/cEOSarm + docker import"
	@echo "# 4. make check-ceos-image"
	@echo "#"
	@echo "# Equivalent ardl one-liner (amd64 example):"
	@echo "#   ARISTA_TOKEN=... ardl get eos --version $(CEOS_VERSION) --format cEOS64 \\"
	@echo "#     --output $(CEOS_DOWNLOAD_DIR) --import-docker \\"
	@echo "#     --docker-name $(CEOS_DOCKER_NAME) --docker-tag $(CEOS_VERSION)"

download-ceos: ## Download and import cEOS via eos-downloader (requires ARISTA_TOKEN)
	@set -euo pipefail; \
	case "$$(uname -m)" in \
		x86_64|amd64)  CEOS_FORMAT=cEOS64; CEOS_TAR="$(CEOS_DOWNLOAD_DIR)/cEOS64-lab-$(CEOS_VERSION).tar.xz" ;; \
		aarch64|arm64) \
			CEOS_FORMAT=cEOSarm; \
			CEOS_TAR="$(CEOS_DOWNLOAD_DIR)/cEOSarm-lab-$(CEOS_VERSION).tar.xz"; \
			if [ ! -f "$$CEOS_TAR" ]; then \
				CEOS_TAR=$$(compgen -G "$(CEOS_DOWNLOAD_DIR)/cEOSarm-lab-$(CEOS_VERSION)"*.tar.xz 2>/dev/null | head -1 || true); \
			fi ;; \
		*) echo "unsupported architecture: $$(uname -m)"; exit 1 ;; \
	esac; \
	if [ -n "$${CEOS_TAR:-}" ] && [ -f "$$CEOS_TAR" ]; then \
		echo "Tarball already present ($$CEOS_TAR); importing without Arista API."; \
		$(MAKE) --no-print-directory import-ceos; \
		exit 0; \
	fi; \
	set -a; [ -f .env ] && . ./.env; set +a; \
	if [ -z "$${ARISTA_TOKEN:-}" ]; then \
		echo "ARISTA_TOKEN not set. Copy .env.example → .env or export token."; \
		echo "Get token: https://www.arista.com/en/users/profile"; \
		echo "Manual fallback: make import-ceos-help"; \
		exit 1; \
	fi; \
	if [ ! -x .venv/bin/python3 ] || ! .venv/bin/python3 -m pip --version >/dev/null 2>&1; then \
		rm -rf .venv && python3 -m venv .venv; \
	fi; \
	ROOT=$$(pwd); \
	PY="$$ROOT/.venv/bin/python3"; \
	if ! "$$PY" -c "import eos_downloader" 2>/dev/null; then \
		"$$PY" -m pip install 'eos-downloader>=0.16.0'; \
	fi; \
	mkdir -p "$(CEOS_DOWNLOAD_DIR)"; \
	cd "$(CEOS_DOWNLOAD_DIR)" && \
	ARISTA_GET_EOS_OUTPUT="." "$$PY" -m eos_downloader.cli.cli --token "$$ARISTA_TOKEN" get eos \
		--version "$(CEOS_VERSION)" \
		--format "$$CEOS_FORMAT" \
		--output "." \
		--import-docker \
		--docker-name "$(CEOS_DOCKER_NAME)" \
		--docker-tag "$(CEOS_VERSION)" || { \
		echo ""; \
		echo "ardl failed contacting the Arista portal (often transient)."; \
		echo "If download/$(CEOS_FORMAT)-lab-$(CEOS_VERSION)*.tar.xz already exists, run: make import-ceos"; \
		exit 1; \
	}

build-radius: $(GEN_CONFIGS) ## Build quantum-safe-radius:latest for the host architecture (buildx --load)
	docker buildx build --load --platform linux/$(HOST_ARCH) -t $(RADIUS_IMAGE) -f $(RADIUS_DOCKERFILE) .
	@$(MAKE) --no-print-directory test-radius-image

test-radius-image: ## Verify quantum-safe-radius:latest (FreeRADIUS 3.2.x + OpenSSL 3.5 PQC + RadSec)
	@set -euo pipefail; \
	echo "FreeRADIUS: $$(docker run --rm $(RADIUS_IMAGE) radiusd -v 2>&1 | head -1)"; \
	echo "OpenSSL:    $$(docker run --rm $(RADIUS_IMAGE) openssl version)"; \
	groups=$$(docker run --rm $(RADIUS_IMAGE) openssl list -tls-groups); \
	for g in X25519MLKEM768 MLKEM768 SecP256r1MLKEM768; do \
		echo "$$groups" | grep -q "$$g" || { echo "missing PQC group: $$g"; exit 1; }; \
		echo "PQC group:  $$g present"; \
	done; \
	docker run --rm $(RADIUS_IMAGE) test -L /etc/raddb/sites-enabled/tls; \
	echo "RadSec:     tls site enabled"; \
	docker run --rm $(RADIUS_IMAGE) radiusd -C >/dev/null; \
	echo "RadSec:     radiusd config OK"

build-syslog: $(GEN_CONFIGS) ## Build quantum-safe-syslog:latest for the host architecture (buildx --load)
	docker buildx build --load --platform linux/$(HOST_ARCH) -t $(SYSLOG_IMAGE) -f $(SYSLOG_DOCKERFILE) .
	@$(MAKE) --no-print-directory test-syslog-image

test-syslog-image: ## Verify quantum-safe-syslog:latest (syslog-ng + OpenSSL 3.5 PQC + TLS listener)
	@set -euo pipefail; \
	echo "OpenSSL:    $$(docker run --rm $(SYSLOG_IMAGE) openssl version)"; \
	groups=$$(docker run --rm $(SYSLOG_IMAGE) openssl list -tls-groups); \
	for g in X25519MLKEM768 MLKEM768 SecP256r1MLKEM768; do \
		echo "$$groups" | grep -q "$$g" || { echo "missing PQC group: $$g"; exit 1; }; \
		echo "PQC group:  $$g present"; \
	done; \
	docker run --rm --entrypoint test $(SYSLOG_IMAGE) -f /etc/syslog-ng/syslog-ng.conf; \
	docker run --rm --entrypoint /opt/syslog-ng/sbin/syslog-ng $(SYSLOG_IMAGE) -s -f /etc/syslog-ng/syslog-ng.conf; \
	docker run --rm --entrypoint test $(SYSLOG_IMAGE) -x /entrypoint.sh; \
	docker run --rm --entrypoint test $(SYSLOG_IMAGE) -x /usr/local/bin/syslog-healthcheck.sh; \
	cid=$$(docker run -d --name quantum-safe-syslog-image-test $(SYSLOG_IMAGE)); \
	trap 'docker rm -f quantum-safe-syslog-image-test >/dev/null 2>&1 || true' EXIT; \
	echo "Syslog:     waiting for TLS healthcheck..."; \
	for i in $$(seq 1 30); do \
		status=$$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' $$cid 2>/dev/null || echo missing); \
		if [ "$$status" = healthy ]; then \
			echo "Syslog:     TLS healthcheck passed"; \
			exit 0; \
		fi; \
		sleep 2; \
	done; \
	echo "syslog image healthcheck did not become healthy (last status: $$status)"; \
	docker logs $$cid 2>&1 | tail -20; \
	exit 1

build-kme: $(GEN_CONFIGS) ## Build quantum-safe-kme:latest for the host architecture (buildx --load)
	docker buildx build --load --platform linux/$(HOST_ARCH) -t $(KME_IMAGE) -f $(KME_DOCKERFILE) .
	@$(MAKE) --no-print-directory test-kme-image

test-kme-image: ## Verify quantum-safe-kme:latest (ETSI QKD 014 simulator)
	@set -euo pipefail; \
	docker run --rm --entrypoint python3 $(KME_IMAGE) -c "from server.app import App; import flask; print('import ok')"; \
	echo "KME:        next-door-key-simulator import OK"; \
	docker run --rm --entrypoint test $(KME_IMAGE) -x /entrypoint.sh; \
	echo "KME:        entrypoint present"

build-test-runner: ## Build quantum-safe-test-runner:latest for the host architecture (buildx --load)
	docker buildx build --load --platform linux/$(HOST_ARCH) -t $(TEST_RUNNER_IMAGE) -f $(TEST_RUNNER_DOCKERFILE) .
	@$(MAKE) --no-print-directory test-test-runner-image

test-test-runner-image: ## Verify quantum-safe-test-runner:latest (OpenSSL 3.5 PQC + curl)
	@set -euo pipefail; \
	echo "OpenSSL:    $$(docker run --rm $(TEST_RUNNER_IMAGE) openssl version)"; \
	groups=$$(docker run --rm $(TEST_RUNNER_IMAGE) openssl list -tls-groups); \
	for g in X25519MLKEM768 MLKEM768 SecP256r1MLKEM768; do \
		echo "$$groups" | grep -q "$$g" || { echo "missing PQC group: $$g"; exit 1; }; \
		echo "PQC group:  $$g present"; \
	done; \
	echo "curl:       $$(docker run --rm $(TEST_RUNNER_IMAGE) curl --version 2>&1 | sed -n '1p')"; \
	docker run --rm $(TEST_RUNNER_IMAGE) sh -c 'curl --version | grep -qi openssl'; \
	echo "Probe:      curl linked to OpenSSL"; \
	echo "OpenSSH:    $$(docker run --rm $(TEST_RUNNER_IMAGE) ssh -V 2>&1 | sed -n '1p')"; \
	docker run --rm $(TEST_RUNNER_IMAGE) sh -c 'ssh -Q kex | grep -q mlkem768x25519-sha256'; \
	echo "Probe:      ssh supports mlkem768x25519-sha256"; \
	echo "gnmic:      $$(docker run --rm $(TEST_RUNNER_IMAGE) gnmic version 2>&1 | sed -n '1p')"

DEPLOY_KME_NODES := kme-a,kme-b

deploy-kme: $(CLAB_TOPO_GEN) ## Deploy KME nodes first (staged; keys need ~30s to generate)
	containerlab deploy -t $(CLAB_TOPO_GEN) --node-filter $(DEPLOY_KME_NODES)

wait-kme-pool: ## Wait for KME key pool after staged deploy (default min 15s, poll 90s)
	@$(PYTHON) -m lab.wait_kme_pool --clab-name '$(CLAB_NAME)' --mgmt-subnet '$(MGMT_SUBNET)' \
		$(if $(filter 1,$(VERBOSE)),--verbose,)

deploy: gen-topo build-radius build-syslog build-kme build-test-runner check-ceos-image ## Deploy lab (KME first, wait for keys, then full topo)
	@$(MAKE) --no-print-directory deploy-kme
	@$(MAKE) --no-print-directory wait-kme-pool VERBOSE=$(VERBOSE)
	containerlab deploy -t $(CLAB_TOPO_GEN)

destroy: $(CLAB_TOPO_GEN) ## Destroy lab and cleanup runtime artifacts
	containerlab destroy -t $(CLAB_TOPO_GEN) --cleanup

clean: ## Full reset: destroy lab, remove artifacts, downloads, Docker images, and build cache
	@set -uo pipefail; \
	echo "=== Destroying lab (if deployed) ==="; \
	if [ -f "$(CLAB_TOPO_GEN)" ]; then \
		containerlab destroy -t $(CLAB_TOPO_GEN) --cleanup 2>/dev/null || true; \
	fi; \
	if command -v docker >/dev/null 2>&1; then \
		ids=$$(docker ps -aq --filter "name=$(CLAB_PREFIX)-$(CLAB_NAME)-" 2>/dev/null || true); \
		if [ -n "$$ids" ]; then \
			echo "Removing leftover $(CLAB_PREFIX)-$(CLAB_NAME)-* containers"; \
			docker rm -f $$ids 2>/dev/null || true; \
		fi; \
		if docker network inspect "$(CLAB_MGMT_NETWORK)" >/dev/null 2>&1; then \
			echo "Removing Docker network $(CLAB_MGMT_NETWORK)"; \
			docker network rm "$(CLAB_MGMT_NETWORK)" 2>/dev/null || true; \
		fi; \
	fi; \
	echo "=== Removing generated topology, PKI, and Containerlab state ==="; \
	rm -rf lab/.gen lab/.gen.* lab/.ceos-monitor lab/clab-* clab-*; \
	echo "=== Cleaning lab logs ==="; \
	find lab/logs/radius -mindepth 1 ! -name '.gitkeep' -print0 2>/dev/null | xargs -0 rm -rf 2>/dev/null || true; \
	find lab/logs/syslog -mindepth 1 ! -name '.gitkeep' -print0 2>/dev/null | xargs -0 rm -rf 2>/dev/null || true; \
	echo "=== Removing download tarballs ==="; \
	rm -rf "$(CEOS_DOWNLOAD_DIR)"; \
	echo "=== Removing Python virtualenv and test caches ==="; \
	rm -rf .venv .pytest_cache; \
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true; \
	echo "=== Removing tmp/ workspace ==="; \
	rm -rf tmp; \
	echo "=== Removing local secrets ==="; \
	rm -f .env; \
	if command -v docker >/dev/null 2>&1; then \
		echo "=== Removing Docker images ==="; \
		for repo in quantum-safe-radius quantum-safe-syslog quantum-safe-kme quantum-safe-test-runner; do \
			tags=$$(docker images "$$repo" --format '{{.Repository}}:{{.Tag}}' 2>/dev/null || true); \
			for tag in $$tags; do \
				echo "  rmi $$tag"; \
				docker rmi "$$tag" 2>/dev/null || true; \
			done; \
		done; \
		if docker image inspect "$(CEOS_IMAGE)" >/dev/null 2>&1; then \
			echo "  rmi $(CEOS_IMAGE)"; \
			docker rmi "$(CEOS_IMAGE)" 2>/dev/null || true; \
		fi; \
		echo "=== Pruning Docker build cache ==="; \
		docker buildx prune -af 2>/dev/null || true; \
	fi; \
	echo "=== Clean complete ==="

redeploy: gen-topo destroy deploy ## Destroy then deploy (gen-topo first so destroy has a local topology file)

inspect: ## Inspect lab node status
	containerlab inspect -t $(CLAB_TOPO_GEN)

graph: ## Render topology graph
	containerlab graph -t $(CLAB_TOPO_GEN)

ssh-ceos1-both: ## Open cEOS CLI on ceos1-both
	docker exec -it $(CLAB_PREFIX)-$(CLAB_NAME)-ceos1-both Cli

ssh-ceos2-pqc: ## Open cEOS CLI on ceos2-pqc
	docker exec -it $(CLAB_PREFIX)-$(CLAB_NAME)-ceos2-pqc Cli

ssh-ceos3-qkd: ## Open cEOS CLI on ceos3-qkd
	docker exec -it $(CLAB_PREFIX)-$(CLAB_NAME)-ceos3-qkd Cli

shell-test-runner: ## Open interactive shell on test-runner probe node
	docker exec -it $(CLAB_PREFIX)-$(CLAB_NAME)-test-runner sh

install-quadra: ## Install QuaDRA swix on ceos1-both and ceos3-qkd (swix in download/quadra/ or QUADRA_SWIX=)
	@env $(if $(QUADRA_SWIX),QUADRA_SWIX='$(QUADRA_SWIX)',) \
		$(if $(filter 1,$(VERBOSE)),VERBOSE=1,-u VERBOSE) $(PYTHON) -m lab.install_quadra --clab-name '$(CLAB_NAME)' \
		$(if $(filter 1,$(VERBOSE)),--verbose,)

test-lab-runner: ## All live lab checks from mgmt-network harness (docker + deployed lab only)
	@set -euo pipefail; \
	if ! docker network inspect "$(CLAB_MGMT_NETWORK)" >/dev/null 2>&1; then \
		echo "Lab mgmt network $(CLAB_MGMT_NETWORK) not found — run make deploy first" >&2; \
		exit 1; \
	fi; \
	docker run --rm \
		-v /var/run/docker.sock:/var/run/docker.sock \
		-v "$(CURDIR):/workspace" \
		-w /workspace \
		--network "$(CLAB_MGMT_NETWORK)" \
		-e CLAB_NAME="$(CLAB_NAME)" \
		-e CLAB_PREFIX="$(CLAB_PREFIX)" \
		-e MGMT_SUBNET="$(MGMT_SUBNET)" \
		$(if $(filter 1,$(VERBOSE)),-e VERBOSE=1,) \
		$(TEST_RUNNER_IMAGE) \
		sh /workspace/docker/test-runner/harness-entrypoint.sh test-lab VERBOSE=$(VERBOSE)

test-lab: ## All live lab checks (requires deployed lab; VERBOSE=1 for command echo)
	@$(MAKE) --no-print-directory VERBOSE=$(VERBOSE) test-radius
	@echo
	@$(MAKE) --no-print-directory VERBOSE=$(VERBOSE) test-kme
	@echo
	@$(MAKE) --no-print-directory VERBOSE=$(VERBOSE) test-pqc
	@echo
	@$(MAKE) --no-print-directory VERBOSE=$(VERBOSE) test-syslog
	@echo
	@$(MAKE) --no-print-directory VERBOSE=$(VERBOSE) test-macsec
	@echo
	@$(MAKE) --no-print-directory VERBOSE=$(VERBOSE) test-qkd
	@echo
	@$(MAKE) --no-print-directory VERBOSE=$(VERBOSE) test-hosts
	@echo
	@echo "✓ All lab checks passed."

test-radius: ## RadSec auth test from both switches (requires deployed lab; VERBOSE=1 for full output)
	@env $(if $(filter 1,$(VERBOSE)),VERBOSE=1,-u VERBOSE) $(LAB_TEST) --section radius

test-kme: ## ETSI QKD 014 checks (requires deployed lab; VERBOSE=1 for full output)
	@env $(if $(filter 1,$(VERBOSE)),VERBOSE=1,-u VERBOSE) $(PYTHON) -m lab.test_kme --clab-name '$(CLAB_NAME)' --mgmt-subnet '$(MGMT_SUBNET)' \
		$(if $(filter 1,$(VERBOSE)),--verbose,)

test-pqc: ## TLS 1.3 + PQC checks incl. syslog-over-TLS (requires deployed lab; VERBOSE=1 for full output)
	@env $(if $(filter 1,$(VERBOSE)),VERBOSE=1,-u VERBOSE) $(PYTHON) -m lab.test_pqc_connections --clab-name '$(CLAB_NAME)' --mgmt-subnet '$(MGMT_SUBNET)' \
		$(if $(filter 1,$(VERBOSE)),--verbose,)

test-syslog: ## PQC syslog-over-TLS checks (requires deployed lab; VERBOSE=1 for full output)
	@env $(if $(filter 1,$(VERBOSE)),VERBOSE=1,-u VERBOSE) $(PYTHON) -m lab.test_syslog --clab-name '$(CLAB_NAME)' --mgmt-subnet '$(MGMT_SUBNET)' \
		$(if $(filter 1,$(VERBOSE)),--verbose,)

test-macsec: ## Dynamic MACsec checks (requires deployed lab; VERBOSE=1 for full output)
	@env $(if $(filter 1,$(VERBOSE)),VERBOSE=1,-u VERBOSE) $(PYTHON) -m lab.test_macsec --clab-name '$(CLAB_NAME)' --mgmt-subnet '$(MGMT_SUBNET)' \
		$(if $(filter 1,$(VERBOSE)),--verbose,) \
		$(if $(filter 1,$(VERIFY_REAUTH)),--verify-reauth,)

test-macsec-reauth: ## MACsec + periodic 802.1X reauth wait (~75s; requires deployed lab)
	@$(MAKE) --no-print-directory VERIFY_REAUTH=1 test-macsec

test-qkd: ## QuaDRA daemon + QKD rotation checks (requires deployed lab; skips when swix absent)
	@env $(if $(filter 1,$(VERBOSE)),VERBOSE=1,-u VERBOSE) $(PYTHON) -m lab.test_qkd --clab-name '$(CLAB_NAME)' \
		$(if $(filter 1,$(VERBOSE)),--verbose,)

test-hosts: ## host routing across all segments (VERBOSE=1 for full output)
	@env $(if $(filter 1,$(VERBOSE)),VERBOSE=1,-u VERBOSE) $(LAB_TEST) --section hosts
