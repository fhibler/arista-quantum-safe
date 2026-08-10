# QKD-MACsec-RADIUS lab — Containerlab lifecycle

SHELL := /bin/bash
.DEFAULT_GOAL := help

CLAB_VERSION  ?= 0.78.0
CEOS_IMAGE ?= ceos:4.36.1F
CEOS_VERSION ?= $(shell echo "$(CEOS_IMAGE)" | cut -d: -f2)
CEOS_DOCKER_NAME ?= $(shell echo "$(CEOS_IMAGE)" | cut -d: -f1)
CEOS_DOWNLOAD_DIR ?= download
CLAB_TOPO_SRC := lab/qkd-macsec-radius.clab.yml
CLAB_TOPO_GEN := lab/.gen.qkd-macsec-radius.clab.yml
CLAB_NAME     := qkd-macsec-radius
MGMT_SUBNET   ?= 172.20.127.0/24
GEN_CONFIGS   := lab/.gen/clients.conf lab/.gen/clients-radsec.conf lab/.gen/ceos1.cfg lab/.gen/ceos2.cfg lab/.gen/kme-radius.conf $(addprefix lab/.gen/pki/,ca.pem server.pem radsec-ca.pem ceos1-client.pem ceos1-client.key ceos1-eapi.pem ceos1-eapi.key ceos1-gnmi.pem ceos1-gnmi.key ceos2-client.pem ceos2-client.key ceos2-eapi.pem ceos2-eapi.key ceos2-gnmi.pem ceos2-gnmi.key) $(addprefix lab/.gen/kme-pki/,ca.crt.pem kme-a.crt.pem kme-a.key.pem kme-b.crt.pem kme-b.key.pem sae.crt.pem sae.key.pem sae-b.crt.pem sae-b.key.pem)
RADIUS_IMAGE  := qkd-radius:latest
RADIUS_DOCKERFILE := docker/radius/Dockerfile
KME_IMAGE     := qkd-kme:latest
KME_DOCKERFILE := docker/kme/Dockerfile
HOST_ARCH     := $(shell uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')
VERBOSE       ?=
PYTHON        := $(shell [ -x .venv/bin/python3 ] && echo .venv/bin/python3 || echo python3)
MGMT_IP_RADIUS = $(shell $(PYTHON) -c "from lab.topology_contract import mgmt_ips_for_subnet; print(mgmt_ips_for_subnet('$(MGMT_SUBNET)')['radius'])")
MGMT_IP_KME_A = $(shell $(PYTHON) -c "from lab.topology_contract import mgmt_ips_for_subnet; print(mgmt_ips_for_subnet('$(MGMT_SUBNET)')['kme-a'])")
MGMT_IP_KME_B = $(shell $(PYTHON) -c "from lab.topology_contract import mgmt_ips_for_subnet; print(mgmt_ips_for_subnet('$(MGMT_SUBNET)')['kme-b'])")
KME_SAE_ID = $(shell $(PYTHON) -c "from lab.topology_contract import KME_SAE_ID; print(KME_SAE_ID)")

LAB_TEST = $(PYTHON) -m lab.test_lab --clab-name '$(CLAB_NAME)' --mgmt-subnet '$(MGMT_SUBNET)' \
	--clab-topo-gen '$(CLAB_TOPO_GEN)' $(if $(filter 1,$(VERBOSE)),--verbose,)

.PHONY: help gen-topo validate-topo sync-devcontainer test check-ceos-image import-ceos import-ceos-help \
        download-ceos download-ceos-help build-radius build-kme deploy-kme-radius wait-kme-pool deploy destroy redeploy \
        inspect graph ssh-ceos1 ssh-ceos2 test-lab test-radius test-kme test-pqc test-macsec test-macsec-reauth test-hosts

help: ## Show available targets
	@grep -E '^[a-zA-Z0-9_-]+:.*##' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  %-20s %s\n", $$1, $$2}'

$(CLAB_TOPO_GEN) $(GEN_CONFIGS): $(CLAB_TOPO_SRC) configs/ceos/ceos1.cfg.in configs/ceos/ceos2.cfg.in configs/radius/raddb/clients.conf.in configs/radius/raddb/clients-radsec.conf.in
	@$(PYTHON) -m lab.render_topo --ceos-image '$(CEOS_IMAGE)' --mgmt-subnet '$(MGMT_SUBNET)'

gen-topo: ## Generate topology YAML with CEOS_IMAGE / MGMT_SUBNET overrides
	@$(PYTHON) -m lab.render_topo --ceos-image '$(CEOS_IMAGE)' --mgmt-subnet '$(MGMT_SUBNET)'
	@$(MAKE) --no-print-directory validate-topo
	@$(MAKE) --no-print-directory sync-devcontainer

sync-devcontainer: ## Sync CLAB_VERSION from Makefile into .devcontainer/devcontainer.json
	@$(PYTHON) -m lab.sync_devcontainer --clab-version '$(CLAB_VERSION)'

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

build-radius: $(GEN_CONFIGS) ## Build qkd-radius:latest for the host architecture (buildx --load)
	docker buildx build --load --platform linux/$(HOST_ARCH) -t $(RADIUS_IMAGE) -f $(RADIUS_DOCKERFILE) .
	@$(MAKE) --no-print-directory test-radius-image

test-radius-image: ## Verify qkd-radius:latest (FreeRADIUS 3.2.x + OpenSSL 3.5 PQC + RadSec)
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

build-kme: $(GEN_CONFIGS) ## Build qkd-kme:latest for the host architecture (buildx --load)
	docker buildx build --load --platform linux/$(HOST_ARCH) -t $(KME_IMAGE) -f $(KME_DOCKERFILE) .
	@$(MAKE) --no-print-directory test-kme-image

test-kme-image: ## Verify qkd-kme:latest (ETSI QKD 014 simulator)
	@set -euo pipefail; \
	docker run --rm --entrypoint python3 $(KME_IMAGE) -c "from server.app import App; import flask; print('import ok')"; \
	echo "KME:        next-door-key-simulator import OK"; \
	docker run --rm --entrypoint test $(KME_IMAGE) -x /entrypoint.sh; \
	echo "KME:        entrypoint present"

DEPLOY_KME_NODES := kme-a,kme-b,radius

deploy-kme-radius: $(CLAB_TOPO_GEN) ## Deploy RADIUS + KME nodes first (staged)
	containerlab deploy -t $(CLAB_TOPO_GEN) --node-filter $(DEPLOY_KME_NODES)

wait-kme-pool: ## Wait for KME key pool after staged deploy (default min 15s, poll 90s)
	@$(PYTHON) -m lab.wait_kme_pool --clab-name '$(CLAB_NAME)' --mgmt-subnet '$(MGMT_SUBNET)' \
		$(if $(filter 1,$(VERBOSE)),--verbose,)

deploy: gen-topo build-radius build-kme check-ceos-image ## Deploy lab (KME/RADIUS first, wait for keys, then full topo)
	@$(MAKE) --no-print-directory deploy-kme-radius
	@$(MAKE) --no-print-directory wait-kme-pool VERBOSE=$(VERBOSE)
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

test-lab: ## All live lab checks (requires deployed lab; use VERBOSE=1 for command echo)
	@$(MAKE) --no-print-directory VERBOSE=$(VERBOSE) test-radius
	@$(MAKE) --no-print-directory VERBOSE=$(VERBOSE) test-kme
	@$(MAKE) --no-print-directory VERBOSE=$(VERBOSE) test-pqc
	@$(MAKE) --no-print-directory VERBOSE=$(VERBOSE) test-macsec
	@$(MAKE) --no-print-directory VERBOSE=$(VERBOSE) test-hosts
	@echo "All lab checks passed."

test-radius: ## RadSec auth test from both switches (requires deployed lab; VERBOSE=1 for full output)
	@VERBOSE='$(VERBOSE)' $(LAB_TEST) --section radius

test-kme: ## ETSI QKD 014 checks (requires deployed lab; VERBOSE=1 for full output)
	@VERBOSE='$(VERBOSE)' $(LAB_TEST) --section kme

test-pqc: ## TLS 1.3 + PQC checks (requires deployed lab; VERBOSE=1 for full output)
	@VERBOSE='$(VERBOSE)' $(PYTHON) -m lab.test_pqc_connections --clab-name '$(CLAB_NAME)' --mgmt-subnet '$(MGMT_SUBNET)' \
		$(if $(filter 1,$(VERBOSE)),--verbose,)

test-macsec: ## Dynamic MACsec checks (requires deployed lab; VERBOSE=1 for full output)
	@VERBOSE='$(VERBOSE)' $(PYTHON) -m lab.test_macsec --clab-name '$(CLAB_NAME)' --mgmt-subnet '$(MGMT_SUBNET)' \
		$(if $(filter 1,$(VERBOSE)),--verbose,) \
		$(if $(filter 1,$(VERIFY_REAUTH)),--verify-reauth,)

test-macsec-reauth: ## MACsec + periodic 802.1X reauth wait (~75s; requires deployed lab)
	@$(MAKE) --no-print-directory VERIFY_REAUTH=1 test-macsec

test-hosts: ## host1 ping host2 across routed segments (VERBOSE=1 for full output)
	@VERBOSE='$(VERBOSE)' $(LAB_TEST) --section hosts
