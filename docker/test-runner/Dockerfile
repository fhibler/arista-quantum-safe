# PQC-capable probe client for live lab checks (curl + OpenSSL 3.5).
#
# Used by the test-runner Containerlab node and the optional test-lab-runner harness.
# OpenSSL is supplied by quantum-safe-openssl:3.5.7-shared (make build-openssl-shared).

ARG ALPINE_VERSION=3.24
ARG OPENSSL_IMAGE=quantum-safe-openssl:3.5.7-shared
ARG CURL_VERSION=8.12.1
ARG OPENSSH_VERSION=10.0p1
ARG GNMIC_VERSION=0.47.0
ARG GRPCURL_VERSION=1.9.3
ARG GO_VERSION=1.25.1
ARG GNOIC_VERSION=0.2.1
ARG GRIBIC_VERSION=0.0.14
ARG GNSIC_VERSION=0.0.4

FROM ${OPENSSL_IMAGE} AS openssl-base

FROM alpine:${ALPINE_VERSION} AS curl-build
ARG CURL_VERSION

# Fetch sources with system TLS only — no custom OpenSSL in this layer.
RUN apk add --no-cache \
      build-base \
      wget \
      tar \
      perl \
      ca-certificates \
      zlib-dev \
      brotli-dev \
      zstd-dev \
      nghttp2-dev \
      c-ares-dev \
      libpsl-dev \
      libidn2-dev \
 && CURL_GITHUB_TAG="curl-$(echo "${CURL_VERSION}" | tr '.' '_')" \
 && set -e; \
    for url in \
      "https://github.com/curl/curl/releases/download/${CURL_GITHUB_TAG}/curl-${CURL_VERSION}.tar.gz" \
      "https://curl.se/download/curl-${CURL_VERSION}.tar.gz"; \
    do \
      wget -q --tries=5 --timeout=60 "$url" -O /tmp/curl.tar.gz && break; \
    done \
 && test -s /tmp/curl.tar.gz \
 && tar -xzf /tmp/curl.tar.gz -C /tmp

COPY --from=openssl-base /opt/openssl /opt/openssl

RUN if [ -f /opt/openssl/lib64/libssl.so ]; then ln -sfn lib64 /opt/openssl/lib; fi

RUN OSSL_LIB=/opt/openssl/lib64; \
    if [ ! -d "$OSSL_LIB" ]; then OSSL_LIB=/opt/openssl/lib; fi; \
    export PATH="/opt/openssl/bin:$PATH"; \
    export PKG_CONFIG_PATH="/opt/openssl/lib/pkgconfig:/opt/openssl/lib64/pkgconfig"; \
    export CPPFLAGS="-I/opt/openssl/include"; \
    export LDFLAGS="-L/opt/openssl/lib -L/opt/openssl/lib64 -Wl,-rpath,/opt/openssl/lib64 -Wl,-rpath,/opt/openssl/lib"; \
    cd "/tmp/curl-${CURL_VERSION}"; \
    ./configure \
      --prefix=/usr/local \
      --with-openssl="/opt/openssl" \
      --with-openssl-includes="/opt/openssl/include" \
      --with-openssl-libs="${OSSL_LIB}" \
      --disable-shared \
      --enable-static \
      --without-libpsl \
      --disable-ldap \
      --disable-ldaps \
      --disable-rtsp \
      --disable-dict \
      --disable-telnet \
      --disable-tftp \
      --disable-pop3 \
      --disable-imap \
      --disable-smb \
      --disable-smtp \
      --disable-gopher \
      --disable-mqtt; \
    make -j"$(nproc)"; \
    make install; \
    /usr/local/bin/curl --version

FROM alpine:${ALPINE_VERSION} AS openssh-build
ARG OPENSSH_VERSION

RUN apk add --no-cache build-base wget tar zlib-dev linux-headers ca-certificates \
 && wget -q --tries=5 --timeout=60 \
      "https://cdn.openbsd.org/pub/OpenBSD/OpenSSH/portable/openssh-${OPENSSH_VERSION}.tar.gz" \
      -O /tmp/openssh.tar.gz \
 && tar -xzf /tmp/openssh.tar.gz -C /tmp

COPY --from=openssl-base /opt/openssl /opt/openssl

RUN if [ -f /opt/openssl/lib64/libssl.so ]; then ln -sfn lib64 /opt/openssl/lib; fi

RUN OSSL_LIB=/opt/openssl/lib64; \
    if [ ! -d "$OSSL_LIB" ]; then OSSL_LIB=/opt/openssl/lib; fi; \
    export PATH="/opt/openssl/bin:$PATH"; \
    export LD_LIBRARY_PATH="/opt/openssl/lib:/opt/openssl/lib64"; \
    export LDFLAGS="-L/opt/openssl/lib -L/opt/openssl/lib64"; \
    export CPPFLAGS="-I/opt/openssl/include"; \
    cd "/tmp/openssh-${OPENSSH_VERSION}"; \
    ./configure \
      --prefix=/usr/local \
      --sysconfdir=/etc/ssh \
      --with-ssl-dir=/opt/openssl \
      --without-pam \
      --without-sandbox \
      --disable-strip; \
    make -j"$(nproc)"; \
    make install; \
    /usr/local/bin/ssh -V; \
    /usr/local/bin/ssh -Q kex | grep -q mlkem768x25519-sha256

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

FROM golang:${GO_VERSION}-alpine AS grpcurl-build
ARG GRPCURL_VERSION
ARG GO_VERSION=1.25.1

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

FROM golang:${GO_VERSION}-alpine AS gribic-build
ARG GRIBIC_VERSION
ARG GO_VERSION=1.25.1

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

# Current Python 3 on latest Alpine. Build stages above stay on ALPINE_VERSION for apk/tool rebuilds.
FROM python:3-alpine

RUN apk add --no-cache \
    ca-certificates \
    docker-cli \
    iputils \
    iproute2 \
    bind-tools \
    tcpdump \
    tshark \
    make \
    bash

COPY requirements-lab.txt /tmp/requirements-lab.txt
RUN pip install --no-cache-dir -r /tmp/requirements-lab.txt \
 && rm -f /tmp/requirements-lab.txt

COPY --from=openssl-base /opt/openssl /opt/openssl
COPY --from=curl-build /usr/local/bin/curl /usr/local/bin/curl
COPY --from=openssh-build /usr/local/bin/ssh /usr/local/bin/ssh
COPY --from=gnmic-fetch /usr/local/bin/gnmic /usr/local/bin/gnmic
COPY --from=grpcurl-build /usr/local/bin/grpcurl /usr/local/bin/grpcurl
COPY --from=gnoic-fetch /usr/local/bin/gnoic /usr/local/bin/gnoic
COPY --from=gribic-build /usr/local/bin/gribic /usr/local/bin/gribic
COPY --from=gnsic-fetch /usr/local/bin/gnsic /usr/local/bin/gnsic

RUN if [ -f /opt/openssl/lib64/libssl.so ]; then ln -sfn lib64 /opt/openssl/lib; fi

ENV PATH=/opt/openssl/bin:/usr/local/bin:$PATH
ENV LD_LIBRARY_PATH=/opt/openssl/lib:/opt/openssl/lib64
ENV OPENSSL_CONF=/etc/probe/openssl-pqc.cnf

RUN mkdir -p /etc/probe/certs

COPY docker/radius/openssl-pqc.cnf /etc/probe/openssl-pqc.cnf

CMD ["sleep", "infinity"]
