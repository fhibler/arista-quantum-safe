# Compile toolchain for FreeRADIUS and syslog-ng build stages only.
# Not a runtime base — do not add python, tshark, docker-cli, or -dev packages here.

ARG ALPINE_VERSION=3.24

FROM alpine:${ALPINE_VERSION}

RUN apk add --no-cache build-base perl linux-headers wget tar git ca-certificates
