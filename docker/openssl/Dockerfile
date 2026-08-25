# OpenSSL 3.5.x built from source for PQC-hybrid TLS (X25519MLKEM768).
#
# Build twice for the two link modes used in lab images:
#   OPENSSL_SHARED=1  -> quantum-safe-openssl:3.5.7-shared  (test-runner: curl, OpenSSH)
#   OPENSSL_SHARED=0  -> quantum-safe-openssl:3.5.7-static  (radius, syslog-ng)

ARG ALPINE_VERSION=3.24
ARG OPENSSL_VERSION=openssl-3.5.7
ARG OPENSSL_SHARED=1

FROM alpine:${ALPINE_VERSION} AS openssl-build
ARG OPENSSL_VERSION
ARG OPENSSL_SHARED
ARG TARGETARCH

RUN apk add --no-cache build-base perl linux-headers wget tar ca-certificates

RUN ARCH="${TARGETARCH:-$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')}" \
 && case "${ARCH}" in \
      amd64)  OPENSSL_TARGET=linux-x86_64 ;; \
      arm64)  OPENSSL_TARGET=linux-aarch64 ;; \
      *) echo "unsupported architecture: ${ARCH}" >&2; exit 1 ;; \
    esac \
 && set -e; \
    for url in \
      "https://github.com/openssl/openssl/releases/download/${OPENSSL_VERSION}/${OPENSSL_VERSION}.tar.gz" \
      "https://www.openssl.org/source/${OPENSSL_VERSION}.tar.gz"; \
    do \
      wget -q --tries=5 --timeout=60 "$url" -O /tmp/openssl.tar.gz && break; \
    done \
 && test -s /tmp/openssl.tar.gz \
 && tar -xzf /tmp/openssl.tar.gz -C /tmp \
 && cd "/tmp/${OPENSSL_VERSION}" \
 && if [ "${OPENSSL_SHARED}" = "1" ]; then \
      ./Configure "${OPENSSL_TARGET}" shared --prefix=/opt/openssl --openssldir=/opt/openssl; \
    else \
      ./Configure "${OPENSSL_TARGET}" no-shared --prefix=/opt/openssl --openssldir=/opt/openssl; \
    fi \
 && make -j"$(nproc)" \
 && make install_sw \
 && if [ "${OPENSSL_SHARED}" = "1" ]; then \
      test -f /opt/openssl/lib64/libssl.so || test -f /opt/openssl/lib/libssl.so; \
    else \
      test -f /opt/openssl/lib64/libcrypto.a || test -f /opt/openssl/lib/libcrypto.a; \
    fi

FROM alpine:${ALPINE_VERSION}

COPY --from=openssl-build /opt/openssl /opt/openssl

RUN if [ -f /opt/openssl/lib64/libssl.so ] || [ -f /opt/openssl/lib64/libcrypto.a ]; then \
      ln -sfn lib64 /opt/openssl/lib; \
    fi

ENV PATH=/opt/openssl/bin:$PATH
