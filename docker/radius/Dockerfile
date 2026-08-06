FROM alpine:3.20 AS radius-arm64
RUN apk add --no-cache freeradius
COPY configs/radius/raddb/clients.conf /etc/raddb/clients.conf
COPY configs/radius/raddb/radiusd.conf /etc/raddb/radiusd-log.conf
COPY configs/radius/raddb/mods-config/files/authorize /etc/raddb/mods-config/files/authorize
RUN printf '\n$INCLUDE radiusd-log.conf\n' >> /etc/raddb/radiusd.conf
CMD ["radiusd", "-f"]

FROM freeradius/freeradius-server:latest-3.2-alpine AS radius-amd64
COPY configs/radius/raddb/clients.conf /etc/raddb/clients.conf
COPY configs/radius/raddb/radiusd.conf /etc/raddb/radiusd-log.conf
COPY configs/radius/raddb/mods-config/files/authorize /etc/raddb/mods-config/files/authorize
RUN printf '\n$INCLUDE radiusd-log.conf\n' >> /etc/raddb/radiusd.conf

FROM radius-${TARGETARCH}
