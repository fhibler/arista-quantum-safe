# Miscellaneous

Reference material that applies across multiple services in the lab.

| Document | Description |
|----------|-------------|
| [Certificates and TLS 1.3](certificates-and-tls13.md) | PKI requirements, server/client certificate fields, and OpenSSL command examples for TLS 1.3 with PQC-hybrid groups |
| [Tool chain](toolchain.md) | OOTB vs lab PQC-safe probe/peer clients; OpenSSL **3.5.0** minimum (lab pin Alpine 3.24 apk **3.5.7**), curl, OpenSSH, and gRPC tool pins |

## Related

- [PQC overview](../pqc-overview.md) — hybrid vs pure PQC, algorithms, OpenSSL 3.5 minimum
- [Services](../services/index.md) — per-service ssl profiles and bindings
- [Setup](../setup.md) — `make gen-topo`, deploy, and PKI generation
