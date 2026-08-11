"""Shared paths and gitignore expectations for repository scaffold tests."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_PATHS = [
    ".gitignore",
    ".env.example",
    "Makefile",
    "lab/quantum-safe.clab.yml",
    "lab/quantum-safe.clab.yml.annotations.json",
    "lab/logs/radius/.gitkeep",
    "lab/logs/syslog/.gitkeep",
    "configs/ceos/ceos1-both.cfg.in",
    "configs/ceos/ceos2-pqc.cfg.in",
    "configs/ceos/ceos3-qkd.cfg.in",
    "configs/radius/raddb/clients.conf.in",
    "configs/radius/raddb/radiusd.conf",
    "configs/radius/raddb/mods-config/files/authorize",
    "configs/syslog/syslog-ng.conf",
    "docker/radius/Dockerfile",
    "docker/syslog/Dockerfile",
    "docker/kme/Dockerfile",
    "docs/syslog.md",
    "docs/verification.md",
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
