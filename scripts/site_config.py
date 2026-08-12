"""Load public site/repository identifiers from site.yaml."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SITE_CONFIG_PATH = REPO_ROOT / "site.yaml"
README_PATH = REPO_ROOT / "README.md"
MKDOCS_PATH = REPO_ROOT / "mkdocs.yml"
README_BEGIN = "<!-- site-config:begin -->"
README_END = "<!-- site-config:end -->"
MKDOCS_BEGIN = "# site-config:begin"
MKDOCS_END = "# site-config:end"


@dataclass(frozen=True)
class SiteConfig:
    repository_host: str
    repository_org: str
    repository_name: str
    default_branch: str
    site_name: str
    site_description: str
    pages_base_url: str

    @property
    def repo_slug(self) -> str:
        return f"{self.repository_org}/{self.repository_name}"

    @property
    def repo_url(self) -> str:
        return f"https://{self.repository_host}/{self.repo_slug}"

    @property
    def pages_base_url_normalized(self) -> str:
        return self.pages_base_url if self.pages_base_url.endswith("/") else f"{self.pages_base_url}/"

    @property
    def edit_uri(self) -> str:
        return f"edit/{self.default_branch}/docs/"

    def pages_url(self, path: str = "") -> str:
        suffix = path.lstrip("/")
        return f"{self.pages_base_url_normalized}{suffix}"


def load_site_config(path: Path | None = None) -> SiteConfig:
    config_path = path or SITE_CONFIG_PATH
    if not config_path.is_file():
        raise FileNotFoundError(f"missing site config: {config_path}")

    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    repository = data.get("repository") or {}
    site = data.get("site") or {}

    required = {
        "repository.host": repository.get("host"),
        "repository.org": repository.get("org"),
        "repository.name": repository.get("name"),
        "repository.default_branch": repository.get("default_branch"),
        "site.name": site.get("name"),
        "site.description": site.get("description"),
        "site.pages_base_url": site.get("pages_base_url"),
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise ValueError(f"site.yaml missing required keys: {', '.join(missing)}")

    return SiteConfig(
        repository_host=str(repository["host"]),
        repository_org=str(repository["org"]),
        repository_name=str(repository["name"]),
        default_branch=str(repository["default_branch"]),
        site_name=str(site["name"]),
        site_description=str(site["description"]),
        pages_base_url=str(site["pages_base_url"]),
    )


def readme_site_config_block(config: SiteConfig) -> str:
    pages = config.pages_base_url_normalized
    return "\n".join(
        (
            README_BEGIN,
            f"**Documentation:** [{pages}]({pages}) (GitHub Pages)",
            "",
            "## Documentation map",
            "",
            "| Topic | Location |",
            "|-------|----------|",
            f"| Setup, Makefile variables, troubleshooting | [Setup guide]({config.pages_url('setup/')}) |",
            f"| Per-service PQC configuration | [Services]({config.pages_url('services/')}) |",
            f"| Live test suite (`make test-lab`) | [Tests]({config.pages_url('tests/')}) |",
            README_END,
        )
    )


def mkdocs_site_config_block(config: SiteConfig) -> str:
    return "\n".join(
        (
            MKDOCS_BEGIN,
            "# Generated from site.yaml — run: make sync-site-config",
            f"site_name: {config.site_name}",
            f"site_description: {config.site_description}",
            f"site_url: {config.pages_base_url_normalized}",
            f"repo_url: {config.repo_url}",
            f"repo_name: {config.repo_slug}",
            f"edit_uri: {config.edit_uri}",
            "extra:",
            "  social:",
            "    - icon: fontawesome/brands/github",
            f"      link: {config.repo_url}",
            MKDOCS_END,
        )
    )


def _replace_marked_block(content: str, *, begin: str, end: str, block: str) -> str:
    if begin in content and end in content:
        before, rest = content.split(begin, 1)
        _, after = rest.split(end, 1)
        return f"{before.rstrip()}\n\n{block}\n{after.lstrip()}"

    if begin.startswith("#"):
        return f"{block}\n\n{content.lstrip()}"

    marker = "## Purpose\n"
    if marker not in content:
        raise ValueError(f"target file missing marker to insert {begin!r}")
    return content.replace(marker, f"{block}\n\n{marker}", 1)


def sync_readme(config: SiteConfig, readme_path: Path = README_PATH) -> bool:
    if not readme_path.is_file():
        raise FileNotFoundError(f"missing README: {readme_path}")

    original = readme_path.read_text(encoding="utf-8")
    updated = _replace_marked_block(
        original,
        begin=README_BEGIN,
        end=README_END,
        block=readme_site_config_block(config),
    )
    if not updated.endswith("\n"):
        updated += "\n"
    if updated == original:
        return False
    readme_path.write_text(updated, encoding="utf-8")
    return True


def sync_mkdocs(config: SiteConfig, mkdocs_path: Path = MKDOCS_PATH) -> bool:
    if not mkdocs_path.is_file():
        raise FileNotFoundError(f"missing mkdocs.yml: {mkdocs_path}")

    original = mkdocs_path.read_text(encoding="utf-8")
    updated = _replace_marked_block(
        original,
        begin=MKDOCS_BEGIN,
        end=MKDOCS_END,
        block=mkdocs_site_config_block(config),
    )
    if not updated.endswith("\n"):
        updated += "\n"
    if updated == original:
        return False
    mkdocs_path.write_text(updated, encoding="utf-8")
    return True


def readme_is_synced(config: SiteConfig, readme_path: Path = README_PATH) -> bool:
    if not readme_path.is_file():
        return False
    return readme_site_config_block(config) in readme_path.read_text(encoding="utf-8")


def mkdocs_is_synced(config: SiteConfig, mkdocs_path: Path = MKDOCS_PATH) -> bool:
    if not mkdocs_path.is_file():
        return False
    return mkdocs_site_config_block(config) in mkdocs_path.read_text(encoding="utf-8")


def sync_all(config: SiteConfig) -> tuple[bool, bool]:
    return sync_readme(config), sync_mkdocs(config)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero when README.md or mkdocs.yml are out of sync with site.yaml",
    )
    parser.add_argument(
        "--sync-readme",
        action="store_true",
        help="Rewrite the README site-config block from site.yaml",
    )
    parser.add_argument(
        "--sync-mkdocs",
        action="store_true",
        help="Rewrite the mkdocs.yml site-config block from site.yaml",
    )
    args = parser.parse_args(argv)

    try:
        config = load_site_config()
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.sync_readme:
        changed = sync_readme(config)
        print("README.md updated." if changed else "README.md already in sync.")
        return 0

    if args.sync_mkdocs:
        changed = sync_mkdocs(config)
        print("mkdocs.yml updated." if changed else "mkdocs.yml already in sync.")
        return 0

    if args.check:
        errors: list[str] = []
        if not readme_is_synced(config):
            errors.append("README.md")
        if not mkdocs_is_synced(config):
            errors.append("mkdocs.yml")
        if errors:
            print(
                f"{', '.join(errors)} out of sync with site.yaml "
                "(run: make sync-site-config)",
                file=sys.stderr,
            )
            return 1
        print("site.yaml, README.md, and mkdocs.yml are in sync.")
        return 0

    print(f"repo_url={config.repo_url}")
    print(f"repo_name={config.repo_slug}")
    print(f"site_url={config.pages_base_url_normalized}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
