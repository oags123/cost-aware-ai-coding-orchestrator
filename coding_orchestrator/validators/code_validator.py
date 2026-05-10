from __future__ import annotations

import sys
from pathlib import Path

from coding_orchestrator.schemas import ValidationResult
from coding_orchestrator.tools.shell import run_limited_command


class SyntaxValidator:
    name = "syntax"

    def __init__(self, cwd: Path, timeout_seconds: int) -> None:
        self.cwd = cwd
        self.timeout_seconds = timeout_seconds

    def validate(self) -> ValidationResult:
        result = run_limited_command(
            [sys.executable, "-m", "compileall", "coding_orchestrator"],
            self.cwd,
            self.timeout_seconds,
            [sys.executable],
        )
        return ValidationResult(
            name=self.name,
            passed=result.returncode == 0,
            message=result.stderr or result.stdout[-1000:],
            details={"returncode": result.returncode},
        )
