"""Shared helpers for VERBOSE=1 lab test output."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from collections.abc import Sequence


def verbose_enabled(explicit: bool | None = None) -> bool:
    if explicit is not None:
        return explicit
    return os.environ.get("VERBOSE") == "1"


def format_output(raw: str) -> str:
    stripped = raw.strip()
    if not stripped:
        return stripped
    try:
        return json.dumps(json.loads(stripped), indent=2, sort_keys=True)
    except json.JSONDecodeError:
        return stripped


def echo_command(title: str, argv: Sequence[str], *, input_text: str = "") -> None:
    print(f"\n--- {title} ---")
    print(f"$ {shlex.join(argv)}")
    if input_text:
        print("--- stdin ---")
        print(input_text.rstrip())
        print("--- end stdin ---")


def echo_result(result: subprocess.CompletedProcess[str], *, format_json: bool = False) -> None:
    if result.stdout:
        print("--- stdout ---")
        body = result.stdout.rstrip()
        print(format_output(body) if format_json else body)
    if result.stderr:
        print("--- stderr ---")
        print(result.stderr.rstrip())
    print(f"--- exit {result.returncode} ---")
