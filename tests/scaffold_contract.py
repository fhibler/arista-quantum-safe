"""Shared paths and gitignore expectations for repository scaffold tests."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_PATHS = [
    ".gitignore",
    ".env.example",
    "Makefile",
    "lab/quantum-safe.clab.yml",
    "lab/logs/radius/.gitkeep",
    "configs/ceos/ceos1-both.cfg.in",
    "configs/ceos/ceos2-pqc.cfg.in",
    "configs/ceos/ceos3-qkd.cfg.in",
    "configs/radius/raddb/clients.conf.in",
    "configs/radius/raddb/radiusd.conf",
    "configs/radius/raddb/mods-config/files/authorize",
    "docker/radius/Dockerfile",
    "docker/kme/Dockerfile",
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
