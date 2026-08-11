# syslog-ng linked against OpenSSL 3.5+ for EOS PQC-hybrid syslog-over-TLS.
#
# EOS ssl profile (example):
#   key-establishment-group X25519MLKEM768:ecdh_x25519:secp256r1
#
# OpenSSL 3.5 negotiates hybrid groups via OPENSSL_CONF (openssl-pqc.cnf).

ARG ALPINE_VERSION=3.20
ARG OPENSSL_VERSION=openssl-3.5.7
ARG SYSLOG_NG_VERSION=4.8.1

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
 && wget -q "https://github.com/openssl/openssl/archive/refs/tags/${OPENSSL_VERSION}.tar.gz" \
      -O /tmp/openssl.tar.gz \
 && tar -xzf /tmp/openssl.tar.gz -C /tmp \
 && cd "/tmp/openssl-openssl-${OPENSSL_VERSION#openssl-}" \
 && ./Configure "${OPENSSL_TARGET}" no-shared --prefix=/opt/openssl --openssldir=/opt/openssl \
 && make -j"$(nproc)" \
 && make install_sw

FROM alpine:${ALPINE_VERSION} AS syslog-ng-build
ARG SYSLOG_NG_VERSION

COPY --from=openssl-build /opt/openssl /opt/openssl

ENV PATH=/opt/openssl/bin:$PATH
ENV LD_LIBRARY_PATH=/opt/openssl/lib
ENV PKG_CONFIG_PATH=/opt/openssl/lib/pkgconfig
ENV CPPFLAGS="-I/opt/openssl/include"
ENV LDFLAGS="-L/opt/openssl/lib -Wl,-rpath,/opt/openssl/lib"

RUN apk add --no-cache build-base wget tar glib-dev curl-dev flex bison json-c-dev pcre2-dev

RUN wget -q "https://github.com/syslog-ng/syslog-ng/releases/download/syslog-ng-${SYSLOG_NG_VERSION}/syslog-ng-${SYSLOG_NG_VERSION}.tar.gz" \
      -O /tmp/syslog-ng.tar.gz \
 && tar -xzf /tmp/syslog-ng.tar.gz -C /tmp \
 && cd "/tmp/syslog-ng-${SYSLOG_NG_VERSION}" \
 && ./configure --prefix=/opt/syslog-ng \
      --sysconfdir=/etc/syslog-ng \
      --enable-tls \
      --with-openssl=/opt/openssl \
      --disable-afuser \
      --disable-python \
      --disable-redis \
      --disable-http \
      --disable-smtp \
      --disable-mongodb \
      --disable-amqp \
      --disable-stomp \
      --disable-glibtest \
      --disable-systemd \
 && make -j"$(nproc)" \
 && make install

FROM alpine:${ALPINE_VERSION}

RUN apk add --no-cache glib libcurl json-c pcre2 libstdc++ tzdata tcpdump

COPY --from=openssl-build /opt/openssl /opt/openssl
COPY --from=syslog-ng-build /opt/syslog-ng /opt/syslog-ng

ENV PATH=/opt/syslog-ng/sbin:/opt/openssl/bin:$PATH
ENV LD_LIBRARY_PATH=/opt/openssl/lib:/opt/syslog-ng/lib
ENV OPENSSL_CONF=/etc/syslog-ng/openssl-pqc.cnf

RUN mkdir -p /etc/syslog-ng/certs /var/log/syslog

COPY docker/syslog/openssl-pqc.cnf /etc/syslog-ng/openssl-pqc.cnf
COPY configs/syslog/syslog-ng.conf /etc/syslog-ng/syslog-ng.conf
COPY lab/.gen/pki/syslog-server.pem /etc/syslog-ng/certs/server.pem
COPY lab/.gen/pki/syslog-server.key /etc/syslog-ng/certs/server.key
COPY lab/.gen/pki/ca.pem /etc/syslog-ng/certs/ca.pem

CMD ["/opt/syslog-ng/sbin/syslog-ng", "-F", "-f", "/etc/syslog-ng/syslog-ng.conf"]
