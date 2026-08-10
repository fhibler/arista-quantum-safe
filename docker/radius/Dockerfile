# FreeRADIUS 3.2.x linked against OpenSSL 3.5+ for EOS PQC-hybrid RadSec.
#
# EOS ssl profile (example):
#   key-establishment-group X25519MLKEM768:ecdh_x25519:secp256r1
#
# OpenSSL 3.5 negotiates hybrid groups via OPENSSL_CONF (openssl-pqc.cnf).

ARG ALPINE_VERSION=3.20
ARG FREERADIUS_VERSION=release_3_2_6
ARG OPENSSL_VERSION=openssl-3.5.7

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

FROM alpine:${ALPINE_VERSION} AS freeradius-build
ARG FREERADIUS_VERSION

COPY --from=openssl-build /opt/openssl /opt/openssl

ENV PATH=/opt/openssl/bin:$PATH
ENV LD_LIBRARY_PATH=/opt/openssl/lib
ENV PKG_CONFIG_PATH=/opt/openssl/lib/pkgconfig
ENV CPPFLAGS="-I/opt/openssl/include"
ENV LDFLAGS="-L/opt/openssl/lib -Wl,-rpath,/opt/openssl/lib"

RUN apk add --no-cache \
    git gcc g++ make musl-dev linux-headers \
    talloc-dev openssl openssl-dev pcre-dev curl-dev json-c-dev perl

RUN git clone --depth 1 --branch "${FREERADIUS_VERSION}" \
    https://github.com/FreeRADIUS/freeradius-server.git /src

WORKDIR /src
RUN ./configure --prefix=/opt/freeradius \
 && make -j"$(nproc)" \
 && make install \
 && rm -f /opt/freeradius/lib/*.a

FROM alpine:${ALPINE_VERSION}

RUN apk add --no-cache talloc pcre libcurl json-c tzdata

COPY --from=openssl-build /opt/openssl /opt/openssl
COPY --from=freeradius-build /opt/freeradius /opt/freeradius

ENV PATH=/opt/openssl/bin:/opt/freeradius/sbin:/opt/freeradius/bin:$PATH
ENV LD_LIBRARY_PATH=/opt/openssl/lib
ENV OPENSSL_CONF=/etc/raddb/openssl-pqc.cnf

RUN ln -sf /opt/freeradius/etc/raddb /etc/raddb \
 && mkdir -p /etc/raddb/certs/radsec \
 && ln -sf ../sites-available/tls /etc/raddb/sites-enabled/tls

COPY docker/radius/openssl-pqc.cnf /etc/raddb/openssl-pqc.cnf
COPY configs/radius/raddb/sites-available/tls /etc/raddb/sites-available/tls
COPY lab/.gen/pki/server.pem /etc/raddb/certs/radsec/server.pem
COPY lab/.gen/pki/ca.pem /etc/raddb/certs/radsec/ca.pem
COPY lab/.gen/clients.conf /etc/raddb/clients.conf
COPY lab/.gen/clients-radsec.conf /etc/raddb/clients-radsec.conf
COPY configs/radius/raddb/radiusd.conf /etc/raddb/radiusd-log.conf
COPY configs/radius/raddb/mods-config/files/authorize /etc/raddb/mods-config/files/authorize
RUN printf '\n$INCLUDE radiusd-log.conf\n' >> /etc/raddb/radiusd.conf

CMD ["radiusd", "-f"]
