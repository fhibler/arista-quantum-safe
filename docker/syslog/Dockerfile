# syslog-ng linked against OpenSSL 3.5+ for EOS PQC-hybrid syslog-over-TLS.
#
# EOS ssl profile (example):
#   key-establishment-group X25519MLKEM768
#
# OpenSSL 3.5 negotiates hybrid groups via OPENSSL_CONF (openssl-pqc.cnf).

ARG ALPINE_VERSION=3.24
ARG OPENSSL_IMAGE=quantum-safe-openssl:3.5.7-static
ARG SYSLOG_NG_VERSION=4.8.1

FROM ${OPENSSL_IMAGE} AS openssl-base

FROM alpine:${ALPINE_VERSION} AS syslog-ng-build
ARG SYSLOG_NG_VERSION

COPY --from=openssl-base /opt/openssl /opt/openssl

RUN if [ -f /opt/openssl/lib64/libcrypto.a ]; then ln -sfn lib64 /opt/openssl/lib; fi

ENV PATH=/opt/openssl/bin:$PATH
ENV LD_LIBRARY_PATH=/opt/openssl/lib:/opt/openssl/lib64
ENV PKG_CONFIG_PATH=/opt/openssl/lib/pkgconfig:/opt/openssl/lib64/pkgconfig
ENV CPPFLAGS="-I/opt/openssl/include"
ENV LDFLAGS="-L/opt/openssl/lib -L/opt/openssl/lib64 -Wl,-rpath,/opt/openssl/lib64 -Wl,-rpath,/opt/openssl/lib"

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

COPY --from=openssl-base /opt/openssl /opt/openssl
COPY --from=syslog-ng-build /opt/syslog-ng /opt/syslog-ng

ENV PATH=/opt/syslog-ng/sbin:/opt/openssl/bin:$PATH
ENV LD_LIBRARY_PATH=/opt/openssl/lib:/opt/openssl/lib64:/opt/syslog-ng/lib
ENV OPENSSL_CONF=/etc/syslog-ng/openssl-pqc.cnf

RUN mkdir -p /etc/syslog-ng/certs /var/log/syslog

COPY docker/syslog/openssl-pqc.cnf /etc/syslog-ng/openssl-pqc.cnf
COPY configs/syslog/syslog-ng.conf /etc/syslog-ng/syslog-ng.conf
COPY lab/.gen/pki/syslog-server.pem /etc/syslog-ng/certs/server.pem
COPY lab/.gen/pki/syslog-server.key /etc/syslog-ng/certs/server.key
COPY lab/.gen/pki/ca.pem /etc/syslog-ng/certs/ca.pem
COPY docker/syslog/entrypoint.sh /entrypoint.sh
COPY docker/syslog/healthcheck.sh /usr/local/bin/syslog-healthcheck.sh
RUN chmod +x /entrypoint.sh /usr/local/bin/syslog-healthcheck.sh

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
	CMD ["/usr/local/bin/syslog-healthcheck.sh"]

ENTRYPOINT ["/entrypoint.sh"]
