"""Colored status markers for lab verification output."""

from __future__ import annotations

import os
import re
import sys
from enum import Enum
from typing import TextIO

ICON_OK = "✓"
ICON_WARN = "⚠"
ICON_FAIL = "✗"

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


_STATUS_ICONS = {
    CheckStatus.OK: ICON_OK,
    CheckStatus.WARN: ICON_WARN,
    CheckStatus.FAIL: ICON_FAIL,
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


def print_section_header(text: str) -> None:
    print(bold(text))


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
    return f"  {status_marker(CheckStatus.OK)} {prefix} {detail}"


def report_check(prefix: str, detail: str, status: CheckStatus = CheckStatus.OK) -> None:
    print(format_check_line(prefix, detail, status))


def report_ok(prefix: str, detail: str) -> None:
    report_check(prefix, detail, CheckStatus.OK)


def report_warn(prefix: str, detail: str) -> None:
    report_check(prefix, detail, CheckStatus.WARN)


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
