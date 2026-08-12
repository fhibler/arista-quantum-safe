"""Shared paths and gitignore expectations for repository scaffold tests."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_PATHS = [
    ".gitignore",
    ".env.example",
    "Makefile",
    "mkdocs.yml",
    "site.yaml",
    "LICENSE",
    ".public-export-ignore",
    "lab/quantum-safe.clab.yml",
    "lab/quantum-safe.clab.yml.annotations.json",
    "lab/logs/radius/.gitkeep",
    "lab/logs/syslog/.gitkeep",
    "configs/ceos/ceos1-both.cfg.in",
    "configs/ceos/ceos2-pqc.cfg.in",
    "configs/ceos/ceos3-qkd.cfg.in",
    "configs/ceos/quadra-daemon-master.cfg.in",
    "configs/ceos/quadra-daemon-slave.cfg.in",
    "configs/ceos/quadra-macsec-master.cfg.in",
    "configs/ceos/quadra-macsec-slave.cfg.in",
    "configs/radius/raddb/clients.conf.in",
    "configs/radius/raddb/radiusd.conf",
    "configs/radius/raddb/mods-config/files/authorize",
    "configs/syslog/syslog-ng.conf",
    "docker/radius/Dockerfile",
    "docker/syslog/Dockerfile",
    "docker/kme/Dockerfile",
    "docs/index.md",
    "docs/setup.md",
    "docs/pqc-overview.md",
    "docs/services/index.md",
    "docs/services/ssh.md",
    "docs/services/qkd-etsi014.md",
    "docs/tests/index.md",
    "internal/PRIVATE",
    "internal/README.md",
    "internal/experimental/README.md",
    "internal/experimental/quadra/QuaDRA EOS extension - User Guide.pdf",
    "internal/experimental/quadra/QuaDRA-1.0.10.rel1-aarch64.swix",
    "internal/experimental/quadra/QuaDRA-1.0.10.rel1-x86_64.swix",
    "internal/docs/syslog.md",
    "internal/docs/quadra.md",
    "internal/docs/verification.md",
    "scripts/check_public_export.py",
    "scripts/export_public.py",
    "scripts/site_config.py",
]

GITIGNORE_PATTERNS = [
    "tmp/**",
    "clab-*/",
    "lab/clab-*/",
    "lab/.gen.*",
    ".env",
    "*.tar.xz",
    "*.sha512sum",
    "download/",
]
