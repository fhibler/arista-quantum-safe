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
    "tests/ssh.md",
    "tests/eapi.md",
    "tests/radsec.md",
    "tests/syslog.md",
    "tests/openconfig.md",
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


CLASSICAL_WIRE_KEX_ROWS = (
    ("gRIBI", "classical (`secp256r1`)", "No"),
    ("gNPSI (TLS)", "classical (`secp256r1`)", "No"),
    ("gNPSI (Subscribe)", "classical (`secp256r1`)", "No"),
    ("Syslog (EOS to collector)", "classical (`x25519`)", "No"),
    ("eos-sdk-rpc (IPv4)", "classical (`secp256r1`)", "No"),
)


def _parse_result_summary_table(text: str) -> dict[str, dict[str, str]]:
    start = text.index("## Result summary")
    end = text.index("**Columns**", start)
    section = text[start:end]
    rows: dict[str, dict[str, str]] = {}
    for line in section.splitlines():
        if not line.startswith("|") or line.startswith("| Service") or line.startswith("|-"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 6:
            continue
        service, _target, tls13, configured, used, pqc_safe = cells[:6]
        rows[service] = {
            "tls13": tls13,
            "configured": configured,
            "used": used,
            "pqc_safe": pqc_safe,
        }
    return rows


def test_result_summary_classical_kex_rows_are_consistent() -> None:
    text = (PUBLIC_DOCS / "tests/index.md").read_text(encoding="utf-8")
    rows = _parse_result_summary_table(text)
    for service, expected_used, expected_pqc_safe in CLASSICAL_WIRE_KEX_ROWS:
        assert service in rows, f"missing result-summary row for {service!r}"
        row = rows[service]
        assert row["used"] == expected_used, service
        assert row["pqc_safe"] == expected_pqc_safe, service
        assert "WARN" not in row["pqc_safe"], f"{service} must not use WARN in PQC-safe column"


def test_openconfig_result_summary_matches_classical_kex_contract() -> None:
    text = (PUBLIC_DOCS / "tests/openconfig.md").read_text(encoding="utf-8")
    start = text.index("## Result summary (EOS 4.36.2F)")
    end = text.index("See also", start)
    section = text[start:end]
    for service, expected_used, expected_pqc_safe in (
        ("gRIBI", "classical (`secp256r1`)", "No"),
        ("gNPSI (TLS)", "classical (`secp256r1`)", "No"),
        ("gNPSI (Subscribe)", "classical (`secp256r1`)", "No"),
        ("eos-sdk-rpc (IPv4)", "classical (`secp256r1`)", "No"),
    ):
        line = next(
            ln for ln in section.splitlines() if ln.startswith(f"| {service} |")
        )
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        assert cells[2] == expected_used, service
        assert cells[3] == expected_pqc_safe, service


TEST_PAGE_CHAPTERS = (
    "## What is checked",
    "## Pass criteria",
    "## Manual reproduction",
)

TEST_PAGES = tuple(p for p in PUBLIC_TEST_DOCS if p != "tests/index.md")


def test_tests_index_documents_chapter_order() -> None:
    text = (PUBLIC_DOCS / "tests/index.md").read_text(encoding="utf-8")
    assert "chapter order" in text
    for heading in ("What is checked", "Pass criteria", "Manual reproduction"):
        assert heading in text, heading
    assert "## Test guides" in text
    guides = text.split("## Test guides", 1)[1]
    for rel_path in TEST_PAGES:
        name = rel_path.removeprefix("tests/")
        assert f"]({name})" in guides, name


@pytest.mark.parametrize("rel_path", TEST_PAGES)
def test_test_page_chapter_order(rel_path: str) -> None:
    text = (PUBLIC_DOCS / rel_path).read_text(encoding="utf-8")
    positions = [text.index(heading) for heading in TEST_PAGE_CHAPTERS]
    assert positions == sorted(positions), rel_path
    assert "<- [Test suite overview](index.md)" in text
    skip_heading = "## Expected SKIP / WARN"
    if skip_heading in text:
        skip_at = text.index(skip_heading)
        assert positions[1] < skip_at < positions[2], rel_path
    checked = text.split("## What is checked", 1)[1].split("## Pass criteria", 1)[0]
    assert "| Type |" in checked or "| `[config]` |" in checked, rel_path


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
