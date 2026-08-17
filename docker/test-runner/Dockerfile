# PQC-capable probe client for live lab checks (curl + OpenSSL 3.5).
#
# Used by the test-runner Containerlab node and the optional test-lab-runner harness.

ARG ALPINE_VERSION=3.20
ARG OPENSSL_VERSION=openssl-3.5.7
ARG CURL_VERSION=8.12.1
ARG OPENSSH_VERSION=10.0p1
ARG GNMIC_VERSION=0.47.0

FROM alpine:${ALPINE_VERSION} AS openssl-build
ARG OPENSSL_VERSION
ARG TARGETARCH

RUN apk add --no-cache build-base perl linux-headers wget tar

RUN ARCH="${TARGETARCH:-$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')}" \
 && case "${ARCH}" in \
      amd64)  OPENSSL_TARGET=linux-x86_64 ;; \
      arm64)  OPENSSL_TARGET=linux-aarch64 ;; \
      *) echo "unsupported architecture: ${ARCH}" >&2; exit 1 ;; \
    esac \
 && wget -q "https://www.openssl.org/source/${OPENSSL_VERSION}.tar.gz" \
      -O /tmp/openssl.tar.gz \
 && tar -xzf /tmp/openssl.tar.gz -C /tmp \
 && cd "/tmp/${OPENSSL_VERSION}" \
 && ./Configure "${OPENSSL_TARGET}" shared --prefix=/opt/openssl --openssldir=/opt/openssl \
 && make -j"$(nproc)" \
 && make install_sw \
 && test -f /opt/openssl/lib64/libssl.so || test -f /opt/openssl/lib/libssl.so

FROM alpine:${ALPINE_VERSION} AS curl-build
ARG CURL_VERSION

COPY --from=openssl-build /opt/openssl /opt/openssl

RUN if [ -f /opt/openssl/lib64/libssl.so ]; then ln -sfn lib64 /opt/openssl/lib; fi

# Fetch sources with system TLS only — do not put custom OpenSSL on LD_LIBRARY_PATH yet.
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
 && wget -q "https://curl.se/download/curl-${CURL_VERSION}.tar.gz" -O /tmp/curl.tar.gz \
 && tar -xzf /tmp/curl.tar.gz -C /tmp

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

COPY --from=openssl-build /opt/openssl /opt/openssl

RUN if [ -f /opt/openssl/lib64/libssl.so ]; then ln -sfn lib64 /opt/openssl/lib; fi \
 && apk add --no-cache build-base wget tar zlib-dev linux-headers \
 && wget -q "https://cdn.openbsd.org/pub/OpenBSD/OpenSSH/portable/openssh-${OPENSSH_VERSION}.tar.gz" \
      -O /tmp/openssh.tar.gz \
 && tar -xzf /tmp/openssh.tar.gz -C /tmp

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

RUN apk add --no-cache wget tar \
 && ARCH="$(case "${TARGETARCH:-$(uname -m)}" in \
      amd64|x86_64) echo x86_64 ;; \
      arm64|aarch64) echo aarch64 ;; \
      *) echo "unsupported architecture: ${TARGETARCH:-$(uname -m)}" >&2; exit 1 ;; \
    esac)" \
 && wget -q "https://github.com/openconfig/gnmic/releases/download/v${GNMIC_VERSION}/gnmic_${GNMIC_VERSION}_Linux_${ARCH}.tar.gz" \
      -O /tmp/gnmic.tar.gz \
 && tar -xzf /tmp/gnmic.tar.gz -C /tmp \
 && install -m 755 /tmp/gnmic /usr/local/bin/gnmic \
 && gnmic version

FROM alpine:${ALPINE_VERSION}

RUN apk add --no-cache \
    ca-certificates \
    docker-cli \
    iputils \
    iproute2 \
    bind-tools \
    tcpdump \
    tshark \
    python3 \
    py3-pip \
    py3-yaml \
    make \
    bash

COPY --from=openssl-build /opt/openssl /opt/openssl
COPY --from=curl-build /usr/local/bin/curl /usr/local/bin/curl
COPY --from=openssh-build /usr/local/bin/ssh /usr/local/bin/ssh
COPY --from=gnmic-fetch /usr/local/bin/gnmic /usr/local/bin/gnmic

RUN if [ -f /opt/openssl/lib64/libssl.so ]; then ln -sfn lib64 /opt/openssl/lib; fi

ENV PATH=/opt/openssl/bin:/usr/local/bin:$PATH
ENV LD_LIBRARY_PATH=/opt/openssl/lib:/opt/openssl/lib64
ENV OPENSSL_CONF=/etc/probe/openssl-pqc.cnf

RUN mkdir -p /etc/probe/certs

COPY docker/radius/openssl-pqc.cnf /etc/probe/openssl-pqc.cnf

CMD ["sleep", "infinity"]
