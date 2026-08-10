# ETSI GS QKD 014 KME simulator — https://github.com/CreepPork/next-door-key-simulator
#
# Multi-arch (linux/amd64, linux/arm64) via buildx --load, matching qkd-radius:latest.

ARG ALPINE_VERSION=3.20
ARG PYTHON_VERSION=3.12
ARG KME_SIMULATOR_REPO=https://github.com/CreepPork/next-door-key-simulator.git
ARG KME_SIMULATOR_REF=master

FROM python:${PYTHON_VERSION}-alpine${ALPINE_VERSION}

ARG KME_SIMULATOR_REPO
ARG KME_SIMULATOR_REF
ARG TARGETARCH

ENV PYTHONUNBUFFERED=1
ENV HOST=0.0.0.0
ENV PORT=8010

RUN apk add --no-cache bash curl git iptables \
 && ARCH="${TARGETARCH:-$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')}" \
 && case "${ARCH}" in \
      amd64|arm64) ;; \
      *) echo "unsupported architecture: ${ARCH}" >&2; exit 1 ;; \
    esac

WORKDIR /opt/next-door-key-simulator
RUN git clone --depth 1 --branch "${KME_SIMULATOR_REF}" "${KME_SIMULATOR_REPO}" . \
 && pip3 install --no-cache-dir -r requirements.txt

COPY docker/kme/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8010

ENTRYPOINT ["/entrypoint.sh"]
