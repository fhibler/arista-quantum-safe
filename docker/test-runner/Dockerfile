# PQC-capable probe client for live lab checks (curl + OpenSSL 3.5).
#
# Used by the test-runner Containerlab node and the optional test-lab-runner harness.
# Alpine 3.24 apk OpenSSL 3.5.7, curl, and openssh-client provide PQC-hybrid TLS/SSH.

ARG ALPINE_VERSION=3.24
ARG GNMIC_VERSION=0.47.0
ARG GRPCURL_VERSION=1.9.3
ARG GO_VERSION=1.27.0
ARG GNOIC_VERSION=0.2.1
ARG GRIBIC_VERSION=0.0.14
ARG GNSIC_VERSION=0.0.4

FROM alpine:${ALPINE_VERSION} AS gnmic-fetch
ARG GNMIC_VERSION
ARG TARGETARCH

RUN apk add --no-cache wget tar ca-certificates \
 && ARCH="$(case "${TARGETARCH:-$(uname -m)}" in \
      amd64|x86_64) echo x86_64 ;; \
      arm64|aarch64) echo aarch64 ;; \
      *) echo "unsupported architecture: ${TARGETARCH:-$(uname -m)}" >&2; exit 1 ;; \
    esac)" \
 && wget -q --tries=5 --timeout=60 \
      "https://github.com/openconfig/gnmic/releases/download/v${GNMIC_VERSION}/gnmic_${GNMIC_VERSION}_Linux_${ARCH}.tar.gz" \
      -O /tmp/gnmic.tar.gz \
 && tar -xzf /tmp/gnmic.tar.gz -C /tmp \
 && install -m 755 /tmp/gnmic /usr/local/bin/gnmic \
 && gnmic version

FROM golang:${GO_VERSION}-alpine${ALPINE_VERSION} AS grpcurl-build
ARG GRPCURL_VERSION
ARG GO_VERSION=1.27.0

RUN apk add --no-cache wget tar ca-certificates \
 && wget -q --tries=5 --timeout=120 \
      "https://github.com/fullstorydev/grpcurl/archive/refs/tags/v${GRPCURL_VERSION}.tar.gz" \
      -O /tmp/grpcurl.tar.gz \
 && tar -xzf /tmp/grpcurl.tar.gz -C /tmp \
 && cd "/tmp/grpcurl-${GRPCURL_VERSION}" \
 && GO_MOD="$(echo "${GO_VERSION}" | sed 's/\.[0-9]*$//')" \
 && go mod edit -go="${GO_MOD}" \
 && CGO_ENABLED=0 GOOS=linux go build \
      -ldflags="-s -w -X main.version=v${GRPCURL_VERSION}" \
      -o /usr/local/bin/grpcurl ./cmd/grpcurl \
 && go version -m /usr/local/bin/grpcurl | grep -qE 'go1\.(2[4-9]|[3-9][0-9])' \
 && /usr/local/bin/grpcurl --version

FROM alpine:${ALPINE_VERSION} AS gnoic-fetch
ARG GNOIC_VERSION
ARG TARGETARCH

RUN apk add --no-cache wget tar ca-certificates \
 && ARCH="$(case "${TARGETARCH:-$(uname -m)}" in \
      amd64|x86_64) echo x86_64 ;; \
      arm64|aarch64) echo aarch64 ;; \
      *) echo "unsupported architecture: ${TARGETARCH:-$(uname -m)}" >&2; exit 1 ;; \
    esac)" \
 && wget -q --tries=5 --timeout=60 \
      "https://github.com/karimra/gnoic/releases/download/v${GNOIC_VERSION}/gnoic_${GNOIC_VERSION}_Linux_${ARCH}.tar.gz" \
      -O /tmp/gnoic.tar.gz \
 && tar -xzf /tmp/gnoic.tar.gz -C /tmp \
 && install -m 755 /tmp/gnoic /usr/local/bin/gnoic \
 && gnoic version

FROM golang:${GO_VERSION}-alpine${ALPINE_VERSION} AS gribic-build
ARG GRIBIC_VERSION
ARG GO_VERSION=1.27.0

RUN apk add --no-cache wget tar ca-certificates \
 && wget -q --tries=5 --timeout=120 \
      "https://github.com/karimra/gribic/archive/refs/tags/v${GRIBIC_VERSION}.tar.gz" \
      -O /tmp/gribic.tar.gz \
 && tar -xzf /tmp/gribic.tar.gz -C /tmp \
 && cd "/tmp/gribic-${GRIBIC_VERSION}" \
 && GO_MOD="$(echo "${GO_VERSION}" | sed 's/\.[0-9]*$//')" \
 && go mod edit -go="${GO_MOD}" \
 && CGO_ENABLED=0 GOOS=linux go build \
      -ldflags="-s -w -X github.com/karimra/gribic/app.version=${GRIBIC_VERSION}" \
      -o /usr/local/bin/gribic . \
 && go version -m /usr/local/bin/gribic | grep -qE 'go1\.(2[4-9]|[3-9][0-9])' \
 && gribic version

FROM alpine:${ALPINE_VERSION} AS gnsic-fetch
ARG GNSIC_VERSION
ARG TARGETARCH

RUN apk add --no-cache wget tar ca-certificates \
 && ARCH="$(case "${TARGETARCH:-$(uname -m)}" in \
      amd64|x86_64) echo x86_64 ;; \
      arm64|aarch64) echo aarch64 ;; \
      *) echo "unsupported architecture: ${TARGETARCH:-$(uname -m)}" >&2; exit 1 ;; \
    esac)" \
 && wget -q --tries=5 --timeout=60 \
      "https://github.com/karimra/gnsic/releases/download/v${GNSIC_VERSION}/gnsic_${GNSIC_VERSION}_Linux_${ARCH}.tar.gz" \
      -O /tmp/gnsic.tar.gz \
 && tar -xzf /tmp/gnsic.tar.gz -C /tmp \
 && install -m 755 /tmp/gnsic /usr/local/bin/gnsic \
 && gnsic version

FROM runtime

RUN apk add --no-cache \
    python3 \
    py3-pip \
    curl \
    openssh-client \
    docker-cli \
    iputils \
    iproute2 \
    bind-tools \
    tcpdump \
    tshark \
    make \
    bash

COPY requirements-lab.txt /tmp/requirements-lab.txt
RUN pip install --break-system-packages --no-cache-dir -r /tmp/requirements-lab.txt \
 && rm -f /tmp/requirements-lab.txt

COPY --from=gnmic-fetch /usr/local/bin/gnmic /usr/local/bin/gnmic
COPY --from=grpcurl-build /usr/local/bin/grpcurl /usr/local/bin/grpcurl
COPY --from=gnoic-fetch /usr/local/bin/gnoic /usr/local/bin/gnoic
COPY --from=gribic-build /usr/local/bin/gribic /usr/local/bin/gribic
COPY --from=gnsic-fetch /usr/local/bin/gnsic /usr/local/bin/gnsic

ENV OPENSSL_CONF=/etc/probe/openssl-pqc.cnf

RUN mkdir -p /etc/probe/certs

COPY docker/radius/openssl-pqc.cnf /etc/probe/openssl-pqc.cnf

CMD ["sleep", "infinity"]
