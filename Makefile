# Quantum Safe lab — Containerlab lifecycle

SHELL := /bin/bash
.DEFAULT_GOAL := help

# Optional local overrides (gitignored). Loaded before ?= defaults below.
-include .env

CLAB_MIN_VERSION ?= 0.78.0
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
VERBOSE       ?=
GEN_CONFIGS   := lab/.gen/clients.conf lab/.gen/clients-radsec.conf lab/.gen/ceos1-both.cfg lab/.gen/ceos2-pqc.cfg lab/.gen/ceos3-qkd.cfg lab/.gen/kme-lab.conf $(addprefix lab/.gen/pki/,ca.pem server.pem radsec-ca.pem syslog-server.pem syslog-server.key ceos1-both-client.pem ceos1-both-client.key ceos1-both-eapi.pem ceos1-both-eapi.key ceos1-both-gnmi.pem ceos1-both-gnmi.key ceos2-pqc-client.pem ceos2-pqc-client.key ceos2-pqc-eapi.pem ceos2-pqc-eapi.key ceos2-pqc-gnmi.pem ceos2-pqc-gnmi.key ceos3-qkd-client.pem ceos3-qkd-client.key ceos3-qkd-eapi.pem ceos3-qkd-eapi.key ceos3-qkd-gnmi.pem ceos3-qkd-gnmi.key) $(addprefix lab/.gen/kme-pki/,ca.crt.pem kme-a.crt.pem kme-a.key.pem kme-b.crt.pem kme-b.key.pem sae.crt.pem sae.key.pem sae-b.crt.pem sae-b.key.pem kme-sae-bundle.pem kme-sae-b-bundle.pem)
RADIUS_IMAGE  := quantum-safe-radius:latest
RADIUS_DOCKERFILE := docker/radius/Dockerfile
SYSLOG_IMAGE  := quantum-safe-syslog:latest
SYSLOG_DOCKERFILE := docker/syslog/Dockerfile
KME_IMAGE     := quantum-safe-kme:latest
KME_DOCKERFILE := docker/kme/Dockerfile
TEST_RUNNER_IMAGE := quantum-safe-test-runner:latest
TEST_RUNNER_DOCKERFILE := docker/test-runner/Dockerfile
OPENSSL_VERSION_TAG := 3.5.7
OPENSSL_SHARED_IMAGE := quantum-safe-openssl:$(OPENSSL_VERSION_TAG)-shared
OPENSSL_STATIC_IMAGE := quantum-safe-openssl:$(OPENSSL_VERSION_TAG)-static
OPENSSL_DOCKERFILE := docker/openssl/Dockerfile
HOST_ARCH     := $(shell uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')
STAMP_DIR := .stamp
OPENSSL_STATIC_STAMP := $(STAMP_DIR)/openssl-static.$(HOST_ARCH)
OPENSSL_SHARED_STAMP := $(STAMP_DIR)/openssl-shared.$(HOST_ARCH)
# VERBOSE=1 in .env or on the command line, e.g. make deploy VERBOSE=1.
# VERBOSE=1 → plain Docker build output and debug containerlab deploy logs.
DOCKER_BUILD_FLAGS := $(if $(filter 1,$(VERBOSE)),--progress=plain,)
CLAB_DEPLOY_FLAGS := $(if $(filter 1,$(VERBOSE)),-d,)
MAKE_VERBOSE := $(if $(filter 1,$(VERBOSE)),VERBOSE=1,)
PYTHON        := $(shell [ -x .venv/bin/python3 ] && echo .venv/bin/python3 || echo python3)
MGMT_IP_RADIUS = $(shell $(PYTHON) -c "from lab.topology_contract import mgmt_ips_for_subnet; print(mgmt_ips_for_subnet('$(MGMT_SUBNET)')['radius'])")
MGMT_IP_KME_A = $(shell $(PYTHON) -c "from lab.topology_contract import mgmt_ips_for_subnet; print(mgmt_ips_for_subnet('$(MGMT_SUBNET)')['kme-a'])")
MGMT_IP_KME_B = $(shell $(PYTHON) -c "from lab.topology_contract import mgmt_ips_for_subnet; print(mgmt_ips_for_subnet('$(MGMT_SUBNET)')['kme-b'])")
KME_SAE_ID = $(shell $(PYTHON) -c "from lab.topology_contract import KME_SAE_ID; print(KME_SAE_ID)")

# Image builds share one builder and tag the same OpenSSL bases — do not run under make -j.
.NOTPARALLEL: build-openssl build-openssl-static build-openssl-shared build-lab-images build-radius build-syslog build-kme build-test-runner

.PHONY: help gen-topo validate-topo sync-site-config test check-ceos-image check-containerlab import-ceos import-ceos-help \
        download-ceos download-ceos-help build-openssl build-lab-images build-radius build-syslog build-kme deploy-kme wait-kme-pool deploy destroy redeploy \
        clean reset inspect ssh-ceos1-both ssh-ceos2-pqc ssh-ceos3-qkd shell-test-runner install-quadra test-lab test-lab-runner test-radsec test-syslog test-kme test-eapi test-ssh test-openconfig test-macsec-dot1x test-macsec-dot1x-reauth test-macsec-qkd test-hosts

help: ## Show available targets
	@grep -hE '^[a-zA-Z0-9_-]+:.*##' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  %-20s %s\n", $$1, $$2}'

$(CLAB_TOPO_GEN) $(GEN_CONFIGS): $(CLAB_TOPO_SRC) $(CLAB_TOPO_ANN) configs/ceos/ceos1-both.cfg.in configs/ceos/ceos2-pqc.cfg.in configs/ceos/ceos3-qkd.cfg.in configs/ceos/quadra-daemon-master.cfg.in configs/ceos/quadra-daemon-slave.cfg.in configs/ceos/quadra-macsec-master.cfg.in configs/ceos/quadra-macsec-slave.cfg.in configs/radius/raddb/clients.conf.in configs/radius/raddb/clients-radsec.conf.in
	@$(PYTHON) -m lab.render_topo --ceos-image '$(CEOS_IMAGE)' --mgmt-subnet '$(MGMT_SUBNET)'

gen-topo: ## Generate topology YAML with CEOS_IMAGE / MGMT_SUBNET overrides (VERBOSE=1 echoes commands)
	@if [ "$(VERBOSE)" = "1" ]; then set -x; fi; \
	env $(if $(QUADRA_SWIX),QUADRA_SWIX='$(QUADRA_SWIX)',) \
		$(PYTHON) -m lab.render_topo --ceos-image '$(CEOS_IMAGE)' --mgmt-subnet '$(MGMT_SUBNET)'
	@$(MAKE) --no-print-directory validate-topo $(MAKE_VERBOSE)

sync-site-config: ## Sync README.md and mkdocs.yml site blocks from site.yaml
	@$(PYTHON) scripts/site_config.py --sync-readme
	@$(PYTHON) scripts/site_config.py --sync-mkdocs

validate-topo: $(CLAB_TOPO_GEN) ## Validate generated topology against contract
	@$(PYTHON) -m lab.validate_topo $(CLAB_TOPO_GEN) --ceos-image '$(CEOS_IMAGE)' --mgmt-subnet '$(MGMT_SUBNET)'

test: ## Run offline pytest (scaffold + contract validation)
	$(PYTHON) -m pytest

check-ceos-image: ## Fail if cEOS image missing or architecture mismatches host
	@set -euo pipefail; \
	if ! docker image inspect "$(CEOS_IMAGE)" >/dev/null 2>&1; then \
		if [ "$(SKIP_CEOS_IMPORT)" = 1 ]; then \
			echo "cEOS image '$(CEOS_IMAGE)' not found locally."; \
			echo ""; \
			$(MAKE) --no-print-directory import-ceos-help; \
			exit 1; \
		fi; \
		echo "cEOS image '$(CEOS_IMAGE)' not found locally; importing from $(CEOS_DOWNLOAD_DIR)/ if present."; \
		$(MAKE) --no-print-directory import-ceos; \
		exit 0; \
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

check-containerlab: ## Fail if containerlab is not installed or older than CLAB_MIN_VERSION
	@set -euo pipefail; \
	clab=$$(command -v containerlab 2>/dev/null || true); \
	if [ -z "$$clab" ]; then \
		echo "Containerlab is not installed (containerlab not found in PATH)."; \
		echo "Install Containerlab $(CLAB_MIN_VERSION)+ (see docs/setup.md)."; \
		exit 1; \
	fi; \
	if [ ! -x "$$clab" ]; then \
		echo "Containerlab is not installed correctly ($$clab is not executable)."; \
		exit 1; \
	fi; \
	if ! version_out=$$(containerlab version 2>&1); then \
		echo "Containerlab is installed but 'containerlab version' failed ($$clab)."; \
		printf '%s\n' "$$version_out"; \
		exit 1; \
	fi; \
	installed=$$(printf '%s\n' "$$version_out" | sed -n 's/^[[:space:]]*version:[[:space:]]*//p' | head -1); \
	if [ -z "$$installed" ]; then \
		echo "Containerlab is installed but version could not be parsed ($$clab)."; \
		printf '%s\n' "$$version_out"; \
		exit 1; \
	fi; \
	if [ "$$(printf '%s\n' "$(CLAB_MIN_VERSION)" "$$installed" | sort -V | head -1)" != "$(CLAB_MIN_VERSION)" ]; then \
		echo "Containerlab $$installed is too old (need >= $(CLAB_MIN_VERSION))."; \
		echo "Rebuild the devcontainer (installs latest) or run: containerlab version upgrade"; \
		exit 1; \
	fi; \
	echo "Containerlab $$installed installed ($$clab, >= $(CLAB_MIN_VERSION))"

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
	$(MAKE) --no-print-directory check-ceos-image SKIP_CEOS_IMPORT=1

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
	if [ -z "$(ARISTA_TOKEN)" ]; then \
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
	ARISTA_GET_EOS_OUTPUT="." "$$PY" -m eos_downloader.cli.cli --token "$(ARISTA_TOKEN)" get eos \
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

build-openssl-shared: $(OPENSSL_SHARED_STAMP) ## Build quantum-safe-openssl:3.5.7-shared (shared libs for test-runner)

$(OPENSSL_SHARED_STAMP): $(OPENSSL_DOCKERFILE)
	@mkdir -p $(STAMP_DIR)
	docker buildx build --load --platform linux/$(HOST_ARCH) $(DOCKER_BUILD_FLAGS) \
		--build-arg OPENSSL_SHARED=1 \
		-t $(OPENSSL_SHARED_IMAGE) -f $(OPENSSL_DOCKERFILE) .
	@touch $@

build-openssl-static: $(OPENSSL_STATIC_STAMP) ## Build quantum-safe-openssl:3.5.7-static (static libs for radius/syslog)

$(OPENSSL_STATIC_STAMP): $(OPENSSL_DOCKERFILE)
	@mkdir -p $(STAMP_DIR)
	docker buildx build --load --platform linux/$(HOST_ARCH) $(DOCKER_BUILD_FLAGS) \
		--build-arg OPENSSL_SHARED=0 \
		-t $(OPENSSL_STATIC_IMAGE) -f $(OPENSSL_DOCKERFILE) .
	@touch $@

build-openssl: build-openssl-static build-openssl-shared ## Build both OpenSSL base images

build-lab-images: build-openssl build-radius build-syslog build-kme build-test-runner ## Build all lab Docker images (OpenSSL bases once, then services)

build-radius: $(GEN_CONFIGS) build-openssl-static ## Build quantum-safe-radius:latest for the host architecture (buildx --load)
	docker buildx build --load --platform linux/$(HOST_ARCH) $(DOCKER_BUILD_FLAGS) \
		--build-arg OPENSSL_IMAGE=$(OPENSSL_STATIC_IMAGE) \
		-t $(RADIUS_IMAGE) -f $(RADIUS_DOCKERFILE) .
	@$(MAKE) --no-print-directory test-radius-image $(MAKE_VERBOSE)

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

build-syslog: $(GEN_CONFIGS) build-openssl-static ## Build quantum-safe-syslog:latest for the host architecture (buildx --load)
	docker buildx build --load --platform linux/$(HOST_ARCH) $(DOCKER_BUILD_FLAGS) \
		--build-arg OPENSSL_IMAGE=$(OPENSSL_STATIC_IMAGE) \
		-t $(SYSLOG_IMAGE) -f $(SYSLOG_DOCKERFILE) .
	@$(MAKE) --no-print-directory test-syslog-image $(MAKE_VERBOSE)

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
	docker buildx build --load --platform linux/$(HOST_ARCH) $(DOCKER_BUILD_FLAGS) \
		-t $(KME_IMAGE) -f $(KME_DOCKERFILE) .
	@$(MAKE) --no-print-directory test-kme-image $(MAKE_VERBOSE)

test-kme-image: ## Verify quantum-safe-kme:latest (ETSI QKD 014 simulator)
	@set -euo pipefail; \
	docker run --rm --entrypoint python3 $(KME_IMAGE) -c "from server.app import App; import flask; print('import ok')"; \
	echo "KME:        next-door-key-simulator import OK"; \
	docker run --rm --entrypoint test $(KME_IMAGE) -x /entrypoint.sh; \
	echo "KME:        entrypoint present"

build-test-runner: build-openssl-shared ## Build quantum-safe-test-runner:latest for the host architecture (buildx --load)
	docker buildx build --load --platform linux/$(HOST_ARCH) $(DOCKER_BUILD_FLAGS) \
		--build-arg OPENSSL_IMAGE=$(OPENSSL_SHARED_IMAGE) \
		--build-arg GO_VERSION=1.25.1 \
		-t $(TEST_RUNNER_IMAGE) -f $(TEST_RUNNER_DOCKERFILE) .
	@$(MAKE) --no-print-directory verify-test-runner-image $(MAKE_VERBOSE)

verify-test-runner-image: ## Verify quantum-safe-test-runner:latest (OpenSSL 3.5 PQC + curl)
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
	echo "gnmic:      $$(docker run --rm $(TEST_RUNNER_IMAGE) gnmic version 2>&1 | sed -n '1p')"; \
	echo "grpcurl:    $$(docker run --rm $(TEST_RUNNER_IMAGE) grpcurl --version 2>&1 | sed -n '1p')"; \
	docker run --rm $(TEST_RUNNER_IMAGE) sh -c 'grpcurl --version 2>&1 | grep -qE "^grpcurl v[0-9]" && strings /usr/local/bin/grpcurl | grep -qE "go1\\.(2[4-9]|[3-9][0-9])"'; \
	echo "Probe:      grpcurl built with Go 1.24+ (PQC-hybrid TLS client)"; \
	echo "gnoic:      $$(docker run --rm $(TEST_RUNNER_IMAGE) gnoic version 2>&1 | sed -n '1p')"; \
	echo "gribic:     $$(docker run --rm $(TEST_RUNNER_IMAGE) gribic version 2>&1 | sed -n '1p')"; \
	docker run --rm $(TEST_RUNNER_IMAGE) sh -c 'gribic version 2>&1 | grep -qE "[0-9]+\\.[0-9]+" && (go version -m /usr/local/bin/gribic 2>/dev/null | grep -qE "go1\\.(2[4-9]|[3-9][0-9])" || strings /usr/local/bin/gribic | grep -qE "go1\\.(2[4-9]|[3-9][0-9])")'; \
	echo "Probe:      gribic built with Go 1.24+ (PQC-hybrid TLS client)"; \
	echo "gnsic:      $$(docker run --rm $(TEST_RUNNER_IMAGE) gnsic version 2>&1 | sed -n '1p')"; \
	echo "docker:     $$(docker run --rm $(TEST_RUNNER_IMAGE) docker --version 2>&1 | sed -n '1p')"

DEPLOY_KME_NODES := kme-a,kme-b

deploy-kme: check-containerlab $(CLAB_TOPO_GEN) ## Deploy KME nodes first (staged; keys need ~30s to generate)
	containerlab deploy -t $(CLAB_TOPO_GEN) --node-filter $(DEPLOY_KME_NODES) $(CLAB_DEPLOY_FLAGS)

wait-kme-pool: ## Wait for KME key pool after staged deploy (default min 15s, poll 90s)
	@$(PYTHON) -m lab.wait_kme_pool --clab-name '$(CLAB_NAME)' --mgmt-subnet '$(MGMT_SUBNET)' \
		$(if $(filter 1,$(VERBOSE)),--verbose,)

deploy: gen-topo build-lab-images check-ceos-image ## Deploy lab (VERBOSE=1: plain Docker build logs + debug containerlab)
	@$(MAKE) --no-print-directory deploy-kme $(MAKE_VERBOSE)
	@$(MAKE) --no-print-directory wait-kme-pool $(MAKE_VERBOSE)
	containerlab deploy -t $(CLAB_TOPO_GEN) $(CLAB_DEPLOY_FLAGS)

destroy: check-containerlab $(CLAB_TOPO_GEN) ## Destroy lab and cleanup runtime artifacts
	containerlab destroy -t $(CLAB_TOPO_GEN) --cleanup

clean: ## Tear down lab and remove build artifacts (keeps download/ and .env)
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
		echo "=== Cleaning lab logs ==="; \
		if docker info >/dev/null 2>&1; then \
			docker run --rm -v "$(CURDIR)/lab/logs:/logs:rw" alpine sh -c \
				'find /logs/radius /logs/syslog -mindepth 1 ! -name .gitkeep -exec rm -rf {} + 2>/dev/null || true'; \
		fi; \
	else \
		find lab/logs/radius lab/logs/syslog -mindepth 1 ! -name '.gitkeep' -print0 2>/dev/null | xargs -0 rm -rf 2>/dev/null || true; \
	fi; \
	echo "=== Removing generated topology, PKI, and Containerlab state ==="; \
	rm -rf lab/.gen lab/.gen.* lab/.ceos-monitor lab/clab-* clab-*; \
	echo "=== Removing Python virtualenv and test caches ==="; \
	rm -rf .venv .pytest_cache; \
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true; \
	echo "=== Removing tmp/ workspace ==="; \
	rm -rf tmp; \
	rm -rf "$(STAMP_DIR)"; \
	if command -v docker >/dev/null 2>&1; then \
		echo "=== Removing Docker images ==="; \
		for repo in quantum-safe-openssl quantum-safe-radius quantum-safe-syslog quantum-safe-kme quantum-safe-test-runner; do \
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
	echo "=== Clean complete (download/ and .env preserved) ==="

reset: clean ## Reset repo to latest commit: discard local edits and remove all gitignored/untracked files
	@set -euo pipefail; \
	if ! command -v git >/dev/null 2>&1; then \
		echo "git not found — cannot reset working tree" >&2; \
		exit 1; \
	fi; \
	echo "=== Resetting git working tree to HEAD ==="; \
	git reset --hard HEAD; \
	git clean -fdx; \
	echo "=== Reset complete ==="

redeploy: gen-topo destroy deploy ## Destroy then deploy (gen-topo first so destroy has a local topology file)

inspect: check-containerlab ## Inspect lab node status
	containerlab inspect -t $(CLAB_TOPO_GEN)

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
	@$(MAKE) --no-print-directory VERBOSE=$(VERBOSE) test-ssh
	@echo
	@$(MAKE) --no-print-directory VERBOSE=$(VERBOSE) test-eapi
	@echo
	@$(MAKE) --no-print-directory VERBOSE=$(VERBOSE) test-radsec
	@echo
	@$(MAKE) --no-print-directory VERBOSE=$(VERBOSE) test-syslog
	@echo
	@$(MAKE) --no-print-directory VERBOSE=$(VERBOSE) test-openconfig
	@echo
	@$(MAKE) --no-print-directory VERBOSE=$(VERBOSE) test-kme
	@echo
	@$(MAKE) --no-print-directory VERBOSE=$(VERBOSE) test-macsec-dot1x
	@echo
	@$(MAKE) --no-print-directory VERBOSE=$(VERBOSE) test-macsec-qkd
	@echo
	@$(MAKE) --no-print-directory VERBOSE=$(VERBOSE) test-hosts
	@echo
	@echo "✓ All lab checks passed."

test-radsec: ## RadSec reachability, AAA, and collector PQC TLS (requires deployed lab; VERBOSE=1 for full output)
	@env $(if $(filter 1,$(VERBOSE)),VERBOSE=1,-u VERBOSE) $(PYTHON) -m lab.test_radsec --clab-name '$(CLAB_NAME)' --mgmt-subnet '$(MGMT_SUBNET)' \
		$(if $(filter 1,$(VERBOSE)),--verbose,)

test-kme: ## ETSI QKD 014 checks (requires deployed lab; VERBOSE=1 for full output)
	@env $(if $(filter 1,$(VERBOSE)),VERBOSE=1,-u VERBOSE) $(PYTHON) -m lab.test_kme --clab-name '$(CLAB_NAME)' --mgmt-subnet '$(MGMT_SUBNET)' \
		$(if $(filter 1,$(VERBOSE)),--verbose,)

test-eapi: ## eAPI HTTPS + command-api PQC checks (requires deployed lab; VERBOSE=1 for full output)
	@env $(if $(filter 1,$(VERBOSE)),VERBOSE=1,-u VERBOSE) $(PYTHON) -m lab.test_eapi --clab-name '$(CLAB_NAME)' --mgmt-subnet '$(MGMT_SUBNET)' \
		$(if $(filter 1,$(VERBOSE)),--verbose,)

test-ssh: ## SSH PQC KEX checks (requires deployed lab; VERBOSE=1 for full output)
	@env $(if $(filter 1,$(VERBOSE)),VERBOSE=1,-u VERBOSE) $(PYTHON) -m lab.test_ssh --clab-name '$(CLAB_NAME)' --mgmt-subnet '$(MGMT_SUBNET)' \
		$(if $(filter 1,$(VERBOSE)),--verbose,)

test-openconfig: ## OpenConfig gRPC + RESTCONF PQC checks (requires deployed lab; VERBOSE=1 for full output)
	@env $(if $(filter 1,$(VERBOSE)),VERBOSE=1,-u VERBOSE) $(PYTHON) -m lab.test_openconfig --clab-name '$(CLAB_NAME)' --mgmt-subnet '$(MGMT_SUBNET)' \
		$(if $(filter 1,$(VERBOSE)),--verbose,)

test-syslog: ## PQC syslog-over-TLS checks (requires deployed lab; VERBOSE=1 for full output)
	@env $(if $(filter 1,$(VERBOSE)),VERBOSE=1,-u VERBOSE) $(PYTHON) -m lab.test_syslog --clab-name '$(CLAB_NAME)' --mgmt-subnet '$(MGMT_SUBNET)' \
		$(if $(filter 1,$(VERBOSE)),--verbose,)

test-macsec-dot1x: ## Dynamic MACsec (802.1X EAP-TLS + MKA) checks (requires deployed lab; VERBOSE=1 for full output)
	@env $(if $(filter 1,$(VERBOSE)),VERBOSE=1,-u VERBOSE) $(PYTHON) -m lab.test_macsec_dot1x --clab-name '$(CLAB_NAME)' --mgmt-subnet '$(MGMT_SUBNET)' \
		$(if $(filter 1,$(VERBOSE)),--verbose,) \
		$(if $(filter 1,$(VERIFY_REAUTH)),--verify-reauth,)

test-macsec-dot1x-reauth: ## 802.1X MACsec + periodic reauth wait (~75s; requires deployed lab)
	@$(MAKE) --no-print-directory VERIFY_REAUTH=1 test-macsec-dot1x

test-macsec-qkd: ## QuaDRA static SAK / QKD rotation checks (requires deployed lab; skips when swix absent)
	@env $(if $(filter 1,$(VERBOSE)),VERBOSE=1,-u VERBOSE) $(PYTHON) -m lab.test_macsec_qkd --clab-name '$(CLAB_NAME)' \
		$(if $(filter 1,$(VERBOSE)),--verbose,)

test-hosts: ## host routing across all segments (VERBOSE=1 for full output)
	@env $(if $(filter 1,$(VERBOSE)),VERBOSE=1,-u VERBOSE) $(PYTHON) -m lab.test_hosts --clab-name '$(CLAB_NAME)' \
		$(if $(filter 1,$(VERBOSE)),--verbose,)

# Export/publish targets live in internal/export.mk (not present in the public mirror).
ifneq ($(wildcard internal/export.mk),)
include internal/export.mk
endif
