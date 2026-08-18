"""README and documentation contract tests."""

from __future__ import annotations

from pathlib import Path

from tests.scaffold_contract import REPO_ROOT

README = REPO_ROOT / "README.md"
INTERNAL_DOCS_INDEX = REPO_ROOT / "internal" / "docs" / "README.md"
INTERNAL_VERIFICATION_DOC = REPO_ROOT / "internal" / "docs" / "verification.md"


def test_readme_has_no_todo_placeholders() -> None:
    content = README.read_text(encoding="utf-8")
    assert "TODO:" not in content
    assert "TODO —" not in content


def test_readme_covers_required_sections() -> None:
    content = README.read_text(encoding="utf-8").lower()
    for fragment in (
        "## purpose",
        "## prerequisites",
        "## quick start",
        "make deploy",
        "make test-lab",
    ):
        assert fragment in content, f"README missing section containing {fragment!r}"


def test_internal_verification_doc_exists() -> None:
    assert INTERNAL_VERIFICATION_DOC.is_file()


def test_internal_verification_doc_lists_checklist() -> None:
    content = INTERNAL_VERIFICATION_DOC.read_text(encoding="utf-8")
    assert "make inspect" in content
    assert "make test-radsec" in content
    assert "make test-eapi" in content
    assert "make test-ssh" in content
    assert "make test-openconfig" in content
    assert "make test-syslog" in content
    assert "make test-macsec-dot1x" in content
    assert "make test-macsec-qkd" in content
    assert "make test-hosts" in content
    assert "Path C" in content


def test_internal_docs_index_links_verification() -> None:
    content = INTERNAL_DOCS_INDEX.read_text(encoding="utf-8")
    assert "verification.md" in content
    assert "syslog.md" in content
