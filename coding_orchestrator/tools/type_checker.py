from __future__ import annotations

from pathlib import Path

from coding_orchestrator.schemas import CommandResult
from coding_orchestrator.tools.shell import run_limited_command


def run_type_checker(cwd: Path, timeout_seconds: int) -> CommandResult:
    return run_limited_command(["mypy", "."], cwd, timeout_seconds, ["mypy"])

