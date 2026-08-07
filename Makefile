# QKD-MACsec-RADIUS lab — Containerlab lifecycle

SHELL := /bin/bash
.DEFAULT_GOAL := help

CEOS_IMAGE ?= ceos:4.36.1F
CEOS_VERSION ?= $(shell echo "$(CEOS_IMAGE)" | cut -d: -f2)
CEOS_DOCKER_NAME ?= $(shell echo "$(CEOS_IMAGE)" | cut -d: -f1)
CEOS_DOWNLOAD_DIR ?= download
CLAB_TOPO_SRC := lab/qkd-macsec-radius.clab.yml
CLAB_TOPO_GEN := lab/.gen.qkd-macsec-radius.clab.yml
CLAB_NAME     := qkd-macsec-radius
MGMT_SUBNET   ?= 172.20.127.0/24
GEN_CONFIGS   := lab/.gen/clients.conf lab/.gen/ceos1.cfg lab/.gen/ceos2.cfg
RADIUS_IMAGE  := qkd-radius:latest
RADIUS_DOCKERFILE := docker/radius/Dockerfile
HOST_ARCH     := $(shell uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')
PYTHON        := $(shell [ -x .venv/bin/python3 ] && echo .venv/bin/python3 || echo python3)
MGMT_IP_RADIUS = $(shell $(PYTHON) -c "from lab.topology_contract import mgmt_ips_for_subnet; print(mgmt_ips_for_subnet('$(MGMT_SUBNET)')['radius'])")

.PHONY: help gen-topo validate-topo test check-ceos-image import-ceos import-ceos-help \
        download-ceos download-ceos-help build-radius deploy destroy redeploy \
        inspect graph ssh-ceos1 ssh-ceos2 test-radius test-hosts

help: ## Show available targets
	@grep -E '^[a-zA-Z0-9_-]+:.*##' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  %-20s %s\n", $$1, $$2}'

$(CLAB_TOPO_GEN) $(GEN_CONFIGS): $(CLAB_TOPO_SRC) configs/ceos/ceos1.cfg.in configs/ceos/ceos2.cfg.in configs/radius/raddb/clients.conf.in
	@$(PYTHON) -m lab.render_topo --ceos-image '$(CEOS_IMAGE)' --mgmt-subnet '$(MGMT_SUBNET)'

gen-topo: ## Generate topology YAML with CEOS_IMAGE / MGMT_SUBNET overrides
	@$(PYTHON) -m lab.render_topo --ceos-image '$(CEOS_IMAGE)' --mgmt-subnet '$(MGMT_SUBNET)'
	@$(MAKE) --no-print-directory validate-topo

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
	if ! .venv/bin/python3 -c "import eos_downloader" 2>/dev/null; then \
		.venv/bin/python3 -m pip install 'eos-downloader>=0.16.0'; \
	fi; \
	mkdir -p "$(CEOS_DOWNLOAD_DIR)"; \
	cd "$(CEOS_DOWNLOAD_DIR)" && \
	ARISTA_GET_EOS_OUTPUT="." ../.venv/bin/ardl --token "$$ARISTA_TOKEN" get eos \
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

build-radius: lab/.gen/clients.conf ## Build qkd-radius:latest for the host architecture (buildx --load)
	docker buildx build --load --platform linux/$(HOST_ARCH) -t $(RADIUS_IMAGE) -f $(RADIUS_DOCKERFILE) .

deploy: gen-topo build-radius check-ceos-image ## Deploy lab (gen-topo → build-radius → check-ceos-image → clab deploy)
	containerlab deploy -t $(CLAB_TOPO_GEN)

destroy: ## Destroy lab and cleanup runtime artifacts
	containerlab destroy -t $(CLAB_TOPO_GEN) --cleanup

redeploy: destroy deploy ## Destroy then deploy

inspect: ## Inspect lab node status
	containerlab inspect -t $(CLAB_TOPO_GEN)

graph: ## Render topology graph
	containerlab graph -t $(CLAB_TOPO_GEN)

ssh-ceos1: ## Open cEOS CLI on ceos1
	docker exec -it clab-$(CLAB_NAME)-ceos1 Cli

ssh-ceos2: ## Open cEOS CLI on ceos2
	docker exec -it clab-$(CLAB_NAME)-ceos2 Cli

test-radius: ## Ping and RADIUS auth test from both switches
	@set -euo pipefail; \
	for node in ceos1 ceos2; do \
		printf 'enable\nping vrf MGMT $(MGMT_IP_RADIUS) repeat 3\n' \
			| docker exec -i clab-$(CLAB_NAME)-$$node Cli \
			| grep -q '0% packet loss'; \
		printf 'enable\ntest aaa group RADIUS server $(MGMT_IP_RADIUS) vrf MGMT key testing123\n' \
			| docker exec -i clab-$(CLAB_NAME)-$$node Cli \
			| grep -q 'successfully authenticated'; \
	done

test-hosts: ## host1 ping host2 across routed segments
	@set -euo pipefail; \
	docker exec clab-$(CLAB_NAME)-host1 ping -c3 10.0.2.1
