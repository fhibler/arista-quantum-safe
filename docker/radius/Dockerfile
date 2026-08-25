# FreeRADIUS 3.2.x linked against Alpine 3.24 OpenSSL 3.5 for EOS PQC-hybrid RadSec.
#
# EOS ssl profile (example):
#   key-establishment-group X25519MLKEM768
#
# OpenSSL 3.5 negotiates hybrid groups via OPENSSL_CONF (openssl-pqc.cnf).
# Rollback to source OpenSSL: make build-radius USE_SOURCE_OPENSSL=1

ARG ALPINE_VERSION=3.24
ARG FREERADIUS_VERSION=release_3_2_6

FROM builder AS freeradius-build
ARG FREERADIUS_VERSION

RUN apk add --no-cache \
    talloc-dev pcre-dev curl-dev json-c-dev \
    openssl openssl-dev

RUN git clone --depth 1 --branch "${FREERADIUS_VERSION}" \
    https://github.com/FreeRADIUS/freeradius-server.git /src

WORKDIR /src
RUN ./configure --prefix=/opt/freeradius \
 && make -j"$(nproc)" \
 && make install \
 && rm -f /opt/freeradius/lib/*.a

FROM runtime

RUN apk add --no-cache talloc pcre libcurl json-c curl

COPY --from=freeradius-build /opt/freeradius /opt/freeradius

ENV PATH=/opt/freeradius/sbin:/opt/freeradius/bin:$PATH
ENV OPENSSL_CONF=/etc/raddb/openssl-pqc.cnf

RUN ln -sf /opt/freeradius/etc/raddb /etc/raddb \
 && mkdir -p /etc/raddb/certs/radsec /var/log/radius \
 && ln -sf ../sites-available/tls /etc/raddb/sites-enabled/tls \
 && ln -sf ../mods-available/eap /etc/raddb/mods-enabled/eap \
 && sed -i 's/^#[[:space:]]*updated = return[[:space:]]*$/updated = return/' /etc/raddb/sites-enabled/default \
 && sed -i 's|^logdir = ${localstatedir}/log/radius|logdir = /var/log/radius|' /etc/raddb/radiusd.conf \
 && sed -i 's/^\tauth = no/\tauth = yes/' /etc/raddb/radiusd.conf \
 && sed -i 's/^\tauth_goodpass = no/\tauth_goodpass = yes/' /etc/raddb/radiusd.conf \
 && sed -i 's/^\tauth_badpass = no/\tauth_badpass = yes/' /etc/raddb/radiusd.conf \
 && sed -i 's/^#[[:space:]]*auth_log[[:space:]]*$/auth_log/' /etc/raddb/sites-enabled/default \
 && sed -i 's|filename = \${radacctdir}/%{%{Packet-Src-IP-Address}:-%{Packet-Src-IPv6-Address}}/auth-detail-%Y%m%d|filename = /var/log/radius/radius-detail.log|' /etc/raddb/mods-enabled/detail.log

COPY docker/radius/openssl-pqc.cnf /etc/raddb/openssl-pqc.cnf
COPY configs/radius/raddb/mods-available/eap /etc/raddb/mods-available/eap
COPY configs/radius/raddb/sites-available/tls /etc/raddb/sites-available/tls
COPY lab/.gen/pki/server.pem /etc/raddb/certs/radsec/server.pem
COPY lab/.gen/pki/ca.pem /etc/raddb/certs/radsec/ca.pem
COPY lab/.gen/clients.conf /etc/raddb/clients.conf
COPY lab/.gen/clients-radsec.conf /etc/raddb/clients-radsec.conf
COPY configs/radius/raddb/radiusd.conf /etc/raddb/radiusd-log.conf
COPY configs/radius/raddb/policy.d/macsec-dot1x /etc/raddb/policy.d/macsec-dot1x
COPY configs/radius/raddb/mods-config/files/authorize /etc/raddb/mods-config/files/authorize
RUN sed -i '/^\tremove_reply_message_if_eap$/i\\tmacsec-dot1x' /etc/raddb/sites-enabled/default
RUN printf '\n$INCLUDE radiusd-log.conf\n' >> /etc/raddb/radiusd.conf

CMD ["radiusd", "-f"]
