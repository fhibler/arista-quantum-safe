"""Public documentation and export-boundary contract tests."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from tests.scaffold_contract import REPO_ROOT

README = REPO_ROOT / "README.md"
MKDOCS = REPO_ROOT / "mkdocs.yml"
PUBLIC_DOCS = REPO_ROOT / "docs"
INTERNAL_ROOT = REPO_ROOT / "internal"

LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")

PUBLIC_SERVICE_DOCS = (
    "services/index.md",
    "services/ssh.md",
    "services/eapi.md",
    "services/openconfig.md",
    "services/syslog.md",
    "services/radius-radsec.md",
    "services/macsec.md",
    "services/qkd-etsi014.md",
)

PUBLIC_REFERENCE_DOCS = (
    "pqc-overview.md",
)

PUBLIC_MISC_DOCS = (
    "misc/index.md",
    "misc/certificates-and-tls13.md",
    "misc/toolchain.md",
)

PUBLIC_TEST_DOCS = (
    "tests/index.md",
    "tests/eapi.md",
    "tests/ssh.md",
    "tests/radsec.md",
    "tests/openconfig.md",
    "tests/syslog.md",
    "tests/kme.md",
    "tests/macsec-dot1x.md",
    "tests/macsec-qkd.md",
    "tests/hosts.md",
)

STALE_TEST_MODULE_PATTERNS = (
    r"lab\.test_macsec(?!_(?:dot1x|qkd))",
    r"lab\.test_qkd\b",
    r"python -m lab\.test_macsec(?!_(?:dot1x|qkd))",
    r"python -m lab\.test_qkd\b",
    r"tests/macsec\.md",
    r"tests/pqc\.md",
    r"tests/radius\.md",
    r"make test-macsec(?!-(?:dot1x|qkd))",
    r"make test-qkd\b",
    r"make test-pqc\b",
    r"make test-radius\b",
    r"lab\.test_lab\b.*host",
)


def test_public_docs_exclude_stale_test_module_refs() -> None:
    for path in sorted(PUBLIC_DOCS.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        for pattern in STALE_TEST_MODULE_PATTERNS:
            assert re.search(pattern, text) is None, (
                f"{path.relative_to(REPO_ROOT)} must not match stale test ref /{pattern}/"
            )


def test_public_readme_has_no_todo_placeholders() -> None:
    content = README.read_text(encoding="utf-8")
    assert "TODO:" not in content
    assert "TODO —" not in content


INTERNAL_ONLY_MAKE_TARGETS = (
    "docs-build",
    "export-public",
    "publish-public",
    "make graph",
)


def test_public_docs_exclude_internal_make_targets() -> None:
    for path in sorted(PUBLIC_DOCS.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        for target in INTERNAL_ONLY_MAKE_TARGETS:
            assert target not in text, (
                f"{path.relative_to(REPO_ROOT)} must not reference removed/internal target {target!r}"
            )
    readme = README.read_text(encoding="utf-8")
    for target in INTERNAL_ONLY_MAKE_TARGETS:
        assert target not in readme, f"README must not reference {target!r}"


def test_public_setup_doc_has_makefile_reference() -> None:
    content = (PUBLIC_DOCS / "setup.md").read_text(encoding="utf-8")
    assert "make help" in content
    assert "## Makefile reference" in content
    assert "mkdocs build --strict" in content


def test_public_readme_covers_required_sections() -> None:
    content = README.read_text(encoding="utf-8").lower()
    for fragment in (
        "## purpose",
        "## prerequisites",
        "## quick start",
        "make deploy",
        "make test-lab",
        "make download-ceos",
    ):
        assert fragment in content, f"README missing {fragment!r}"


@pytest.mark.parametrize("rel_path", PUBLIC_REFERENCE_DOCS)
def test_public_reference_doc_exists(rel_path: str) -> None:
    assert (PUBLIC_DOCS / rel_path).is_file()


@pytest.mark.parametrize("rel_path", PUBLIC_MISC_DOCS)
def test_public_misc_doc_exists(rel_path: str) -> None:
    assert (PUBLIC_DOCS / rel_path).is_file()


@pytest.mark.parametrize("rel_path", PUBLIC_SERVICE_DOCS)
def test_public_service_doc_exists(rel_path: str) -> None:
    assert (PUBLIC_DOCS / rel_path).is_file()


@pytest.mark.parametrize("rel_path", PUBLIC_TEST_DOCS)
def test_public_test_doc_exists(rel_path: str) -> None:
    assert (PUBLIC_DOCS / rel_path).is_file()


def test_mkdocs_nav_matches_public_docs() -> None:
    text = MKDOCS.read_text(encoding="utf-8")
    for rel_path in (
        *PUBLIC_SERVICE_DOCS,
        *PUBLIC_TEST_DOCS,
        *PUBLIC_REFERENCE_DOCS,
        *PUBLIC_MISC_DOCS,
        "index.md",
        "setup.md",
    ):
        assert rel_path in text, f"mkdocs.yml nav missing {rel_path}"


def test_internal_tree_is_marked_private() -> None:
    assert (INTERNAL_ROOT / "PRIVATE").is_file()
    assert (INTERNAL_ROOT / "docs" / "README.md").is_file()
    assert (INTERNAL_ROOT / "experimental").is_dir()


def test_mkdocs_build_strict() -> None:
    try:
        result = subprocess.run(
            ["mkdocs", "build", "--strict"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        pytest.skip("mkdocs not installed")
    if result.returncode != 0 and "No such file or directory: 'mkdocs'" in (
        result.stderr or result.stdout
    ):
        pytest.skip("mkdocs not installed")
    combined = f"{result.stdout}\n{result.stderr}"
    for pattern in (
        "is not found among documentation files",
        "does not contain an anchor",
    ):
        assert pattern not in combined, combined
    assert result.returncode == 0, combined


def _resolve_doc_link(source: Path, target: str) -> Path | None:
    if target.startswith(("http://", "https://", "mailto:")):
        return None
    path_part = target.split("#", 1)[0]
    if not path_part:
        return source
    candidate = (source.parent / path_part).resolve()
    docs_root = PUBLIC_DOCS.resolve()
    if docs_root not in candidate.parents and candidate != docs_root:
        return None
    return candidate


def test_public_doc_relative_links_resolve() -> None:
    missing: list[str] = []
    for path in sorted(PUBLIC_DOCS.rglob("*.md")):
        for match in LINK_RE.finditer(path.read_text(encoding="utf-8")):
            target = match.group(1).strip()
            resolved = _resolve_doc_link(path, target)
            if resolved is None:
                continue
            if not resolved.is_file():
                rel_source = path.relative_to(REPO_ROOT)
                missing.append(f"{rel_source}: {target!r} -> {resolved.relative_to(REPO_ROOT)}")
    assert not missing, "broken relative links:\n" + "\n".join(missing)
