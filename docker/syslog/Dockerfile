# syslog-ng linked against Alpine 3.24 OpenSSL 3.5 for EOS PQC-hybrid syslog-over-TLS.
#
# EOS ssl profile (example):
#   key-establishment-group X25519MLKEM768
#
# OpenSSL 3.5 negotiates hybrid groups via OPENSSL_CONF (openssl-pqc.cnf).
# Alpine pin is docker-bake.hcl → docker/base (FROM builder / FROM runtime).

ARG SYSLOG_NG_VERSION=4.8.1

FROM builder AS syslog-ng-build
ARG SYSLOG_NG_VERSION

RUN apk add --no-cache glib-dev curl-dev flex bison json-c-dev pcre2-dev openssl-dev

RUN wget -q "https://github.com/syslog-ng/syslog-ng/releases/download/syslog-ng-${SYSLOG_NG_VERSION}/syslog-ng-${SYSLOG_NG_VERSION}.tar.gz" \
      -O /tmp/syslog-ng.tar.gz \
 && tar -xzf /tmp/syslog-ng.tar.gz -C /tmp \
 && cd "/tmp/syslog-ng-${SYSLOG_NG_VERSION}" \
 && ./configure --prefix=/opt/syslog-ng \
      --sysconfdir=/etc/syslog-ng \
      --enable-tls \
      --with-openssl=/usr \
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

FROM runtime

RUN apk add --no-cache glib libcurl json-c pcre2 libstdc++ tcpdump

COPY --from=syslog-ng-build /opt/syslog-ng /opt/syslog-ng

ENV PATH=/opt/syslog-ng/sbin:$PATH
ENV LD_LIBRARY_PATH=/opt/syslog-ng/lib
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
