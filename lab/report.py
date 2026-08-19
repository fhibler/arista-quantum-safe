"""Colored status markers for lab verification output."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from enum import Enum
from typing import TextIO

ICON_OK = "✓"
ICON_WARN = "⚠"
ICON_FAIL = "✗"
ICON_SKIP = "−"

GREEN = "\033[32m"
BRIGHT_ORANGE = "\033[38;5;214m"
BRIGHT_RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"

_ANSI_ESCAPE = re.compile(r"\033\[[0-9;]*(?:;[0-9]+)*m")


class CheckStatus(Enum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


@dataclass
class CheckStats:
    ok: int = 0
    warn: int = 0
    fail: int = 0
    skip: int = 0

    def record(self, status: CheckStatus) -> None:
        if status is CheckStatus.OK:
            self.ok += 1
        elif status is CheckStatus.WARN:
            self.warn += 1
        elif status is CheckStatus.FAIL:
            self.fail += 1
        elif status is CheckStatus.SKIP:
            self.skip += 1


_check_stats = CheckStats()


def reset_check_stats() -> None:
    global _check_stats
    _check_stats = CheckStats()


def check_stats() -> CheckStats:
    return _check_stats


def format_check_counts(stats: CheckStats | None = None) -> str:
    stats = stats or _check_stats
    parts: list[str] = []
    if stats.ok:
        parts.append(f"{stats.ok} passed")
    if stats.warn:
        parts.append(f"{stats.warn} warning{'s' if stats.warn != 1 else ''}")
    if stats.fail:
        parts.append(f"{stats.fail} failed")
    if stats.skip:
        parts.append(f"{stats.skip} skipped")
    return ", ".join(parts) if parts else "0 checks"


_STATUS_ICONS = {
    CheckStatus.OK: ICON_OK,
    CheckStatus.WARN: ICON_WARN,
    CheckStatus.FAIL: ICON_FAIL,
    CheckStatus.SKIP: ICON_SKIP,
}


def colors_enabled() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return sys.stdout.isatty() or sys.stderr.isatty()


def bold(text: str, *, use_colors: bool | None = None) -> str:
    use = colors_enabled() if use_colors is None else use_colors
    if not use:
        return text
    return f"{BOLD}{text}{RESET}"


TEST_HEADER_BORDER = "=" * 42


def print_section_header(text: str) -> None:
    print(bold(text))


def print_test_header(title: str, *description_lines: str) -> None:
    """Print a prominent bordered header for a lab test command."""
    print(TEST_HEADER_BORDER)
    print(bold(title))
    for line in description_lines:
        print(line)
    print(TEST_HEADER_BORDER)
    print()


def print_device(name: str) -> None:
    """Print a bold device or subsection header."""
    print_section_header(f"=== {name} ===")


def print_check_group(name: str) -> None:
    """Print a check-type subsection header (e.g. eAPI, SSH)."""
    print(f"--- {name} ---")


def status_marker(status: CheckStatus, *, use_colors: bool | None = None) -> str:
    icon = _STATUS_ICONS[status]
    use = colors_enabled() if use_colors is None else use_colors
    if not use:
        return icon
    if status is CheckStatus.OK:
        return f"{GREEN}{icon}{RESET}"
    if status is CheckStatus.WARN:
        return f"{BOLD}{BRIGHT_ORANGE}{icon}{RESET}"
    return f"{BOLD}{BRIGHT_RED}{icon}{RESET}"


def visible_len(text: str) -> int:
    return len(_ANSI_ESCAPE.sub("", text))


def align_right(text: str, width: int) -> str:
    padding = max(0, width - visible_len(text))
    return f"{' ' * padding}{text}"


def _emphasize(text: str, status: CheckStatus) -> str:
    if not colors_enabled():
        return text
    if status is CheckStatus.WARN:
        return f"{BOLD}{BRIGHT_ORANGE}{text}{RESET}"
    if status is CheckStatus.FAIL:
        return f"{BOLD}{BRIGHT_RED}{text}{RESET}"
    return text


def format_check_line(prefix: str, detail: str, status: CheckStatus = CheckStatus.OK) -> str:
    if status is CheckStatus.WARN:
        body = f"  {ICON_WARN} WARN {prefix} {detail}"
        return _emphasize(body, CheckStatus.WARN)
    if status is CheckStatus.FAIL:
        body = f"  {ICON_FAIL} FAIL {prefix} {detail}"
        return _emphasize(body, CheckStatus.FAIL)
    if status is CheckStatus.SKIP:
        return f"  {ICON_SKIP} SKIP {prefix} {detail}"
    return f"  {status_marker(CheckStatus.OK)} {prefix} {detail}"


def report_check(prefix: str, detail: str, status: CheckStatus = CheckStatus.OK) -> None:
    check_stats().record(status)
    print(format_check_line(prefix, detail, status))


def report_ok(prefix: str, detail: str) -> None:
    report_check(prefix, detail, CheckStatus.OK)


def report_warn(prefix: str, detail: str) -> None:
    report_check(prefix, detail, CheckStatus.WARN)


def report_skip(prefix: str, detail: str) -> None:
    report_check(prefix, detail, CheckStatus.SKIP)


def format_summary(name: str, detail: str, status: CheckStatus) -> str:
    if status is CheckStatus.FAIL:
        body = f"{name} FAILED: {ICON_FAIL} — {detail}"
        return _emphasize(body, CheckStatus.FAIL)
    return f"{name}: {status_marker(CheckStatus.OK)} — {detail}"


def report_summary(
    name: str,
    detail: str,
    status: CheckStatus = CheckStatus.OK,
    *,
    file: TextIO | None = None,
) -> None:
    print(format_summary(name, detail, status), file=file)


def report_check_summary(name: str, *, file: TextIO | None = None) -> None:
    """Print a suite summary from accumulated check counts (passed/warning/failed/skipped)."""
    stats = check_stats()
    status = CheckStatus.FAIL if stats.fail else CheckStatus.OK
    report_summary(name, format_check_counts(stats), status, file=file)
