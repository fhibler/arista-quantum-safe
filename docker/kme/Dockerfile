# ETSI GS QKD 014 KME simulator — https://github.com/CreepPork/next-door-key-simulator
#
# Multi-arch (linux/amd64, linux/arm64) via buildx --load, matching quantum-safe-radius:latest.

ARG ALPINE_VERSION=3.24
ARG KME_SIMULATOR_REPO=https://github.com/CreepPork/next-door-key-simulator.git
ARG KME_SIMULATOR_REF=master

FROM alpine:${ALPINE_VERSION}

ARG KME_SIMULATOR_REPO
ARG KME_SIMULATOR_REF
ARG TARGETARCH

ENV PYTHONUNBUFFERED=1
ENV HOST=::
ENV PORT=8010

RUN apk add --no-cache bash curl git iptables libffi python3 py3-pip \
 && ARCH="${TARGETARCH:-$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')}" \
 && case "${ARCH}" in \
      amd64|arm64) ;; \
      *) echo "unsupported architecture: ${ARCH}" >&2; exit 1 ;; \
    esac

WORKDIR /opt/next-door-key-simulator
# Alpine apk python3 (3.14) has no musllinux wheels for cffi; compile it, then drop gcc.
RUN apk add --no-cache --virtual .build-deps gcc musl-dev libffi-dev \
 && git clone --depth 1 --branch "${KME_SIMULATOR_REF}" "${KME_SIMULATOR_REPO}" . \
 && pip3 install --break-system-packages --no-cache-dir -r requirements.txt \
 && apk del .build-deps

# Upstream scanner holds kme_lock during peer HTTP calls, deadlocking mutual scans.
COPY docker/kme/scanner.py /opt/next-door-key-simulator/network/scanner.py

COPY docker/kme/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8010

ENTRYPOINT ["/entrypoint.sh"]
