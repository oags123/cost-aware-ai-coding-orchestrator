from __future__ import annotations

import shlex
from pathlib import Path

from coding_orchestrator.schemas import CommandResult
from coding_orchestrator.tools.shell import run_limited_command


def run_validation_command(command: str, cwd: Path, timeout_seconds: int) -> CommandResult:
    parts = shlex.split(command)
    return run_limited_command(
        parts,
        cwd,
        timeout_seconds,
        ["pytest", "ruff", "mypy", "python", "python3"],
    )


def run_tests(cwd: Path, timeout_seconds: int, target: str | None = None) -> CommandResult:
    command = ["pytest"]
    if target:
        command.append(target)
    return run_limited_command(command, cwd, timeout_seconds, ["pytest"])
