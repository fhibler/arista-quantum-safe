"""README and documentation contract tests."""

from __future__ import annotations

from pathlib import Path

from tests.scaffold_contract import REPO_ROOT

README = REPO_ROOT / "README.md"
DOCS_INDEX = REPO_ROOT / "docs" / "README.md"
VERIFICATION_DOC = REPO_ROOT / "docs" / "verification.md"


def test_readme_has_no_todo_placeholders() -> None:
    content = README.read_text(encoding="utf-8")
    assert "TODO:" not in content
    assert "TODO —" not in content


def test_readme_covers_required_sections() -> None:
    content = README.read_text(encoding="utf-8").lower()
    for fragment in (
        "## overview",
        "## prerequisites",
        "## ceos import",
        "## freeradius multi-arch",
        "## quick start",
        "## topology",
        "## verification",
        "## multi-arch notes",
        "## troubleshooting",
    ):
        assert fragment in content, f"README missing section containing {fragment!r}"

def test_verification_doc_exists() -> None:
    assert VERIFICATION_DOC.is_file()


def test_verification_doc_lists_checklist() -> None:
    content = VERIFICATION_DOC.read_text(encoding="utf-8")
    assert "make inspect" in content
    assert "make test-radius" in content
    assert "make test-pqc" in content
    assert "make test-hosts" in content
    assert "Path C" in content


def test_docs_index_links_verification() -> None:
    content = DOCS_INDEX.read_text(encoding="utf-8")
    assert "verification.md" in content
