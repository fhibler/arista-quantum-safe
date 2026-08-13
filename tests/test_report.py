"""Unit tests for colored lab report helpers."""

from __future__ import annotations

from lab.report import (
    ICON_FAIL,
    ICON_OK,
    ICON_SKIP,
    ICON_WARN,
    BRIGHT_ORANGE,
    BRIGHT_RED,
    BOLD,
    GREEN,
    CheckStatus,
    align_right,
    bold,
    colors_enabled,
    format_check_line,
    format_summary,
    print_section_header,
    report_check,
    status_marker,
    visible_len,
)


def test_status_markers_without_color(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    assert status_marker(CheckStatus.OK) == ICON_OK
    assert status_marker(CheckStatus.WARN) == ICON_WARN
    assert status_marker(CheckStatus.FAIL) == ICON_FAIL
    assert status_marker(CheckStatus.SKIP) == ICON_SKIP


def test_status_markers_with_color(monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert GREEN in status_marker(CheckStatus.OK)
    assert BOLD in status_marker(CheckStatus.WARN)
    assert BRIGHT_ORANGE in status_marker(CheckStatus.WARN)
    assert BOLD in status_marker(CheckStatus.FAIL)
    assert BRIGHT_RED in status_marker(CheckStatus.FAIL)


def test_format_summary_uses_status_marker(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    assert format_summary("PQC", "all checks passed", CheckStatus.OK) == "PQC: ✓ — all checks passed"
    assert (
        format_summary("PQC", "handshake failed", CheckStatus.FAIL)
        == "PQC FAILED: ✗ — handshake failed"
    )


def test_format_check_line_warn_is_prominent(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    line = format_check_line("[live]  ", "classical fallback", CheckStatus.WARN)
    assert line == f"  {ICON_WARN} WARN [live]   classical fallback"


def test_format_check_line_warn_uses_bold_color(monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    line = format_check_line("[live]  ", "classical fallback", CheckStatus.WARN)
    assert BOLD in line
    assert BRIGHT_ORANGE in line
    assert "WARN" in line


def test_report_check_prints_marker(capsys, monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    report_check("[live]  ", "SSH ok", CheckStatus.OK)
    report_check("[live]  ", "classical fallback", CheckStatus.WARN)
    output = capsys.readouterr().out
    assert f"  {ICON_OK} [live]   SSH ok" in output
    assert f"  {ICON_WARN} WARN [live]   classical fallback" in output


def test_format_check_line_skip(capsys, monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    line = format_check_line("[live / test-runner]  ", "eos-sdk-rpc IPv6 skipped", CheckStatus.SKIP)
    assert line == f"  {ICON_SKIP} SKIP [live / test-runner]   eos-sdk-rpc IPv6 skipped"


def test_colors_enabled_respects_no_color(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    assert colors_enabled() is False


def test_align_right_ignores_ansi(monkeypatch) -> None:
    monkeypatch.setenv("FORCE_COLOR", "1")
    cell = status_marker(CheckStatus.OK)
    assert visible_len(cell) == 1
    assert align_right(cell, 5) == f"    {cell}"


def test_bold_wraps_text_when_color_enabled(monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert BOLD in bold("PQC verification")
    assert "PQC verification" in bold("PQC verification")


def test_bold_is_plain_without_color(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    assert bold("PQC verification") == "PQC verification"


def test_print_section_header(capsys, monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    print_section_header("KME verification (ETSI QKD 014)")
    assert capsys.readouterr().out == "KME verification (ETSI QKD 014)\n"

