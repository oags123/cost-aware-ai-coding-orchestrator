from __future__ import annotations

import sys
from pathlib import Path

from coding_orchestrator.schemas import ValidationResult
from coding_orchestrator.tools.shell import run_limited_command


class SyntaxValidator:
    name = "syntax"

    def __init__(self, changed_files: list[str], cwd: Path, timeout_seconds: int) -> None:
        self.changed_files = changed_files
        self.cwd = cwd
        self.timeout_seconds = timeout_seconds

    def validate(self) -> ValidationResult:
        python_files = [path for path in self.changed_files if path.endswith(".py")]
        if not python_files:
            return ValidationResult(
                name=self.name,
                passed=True,
                message="no changed Python files to compile-check",
                details={"returncode": 0},
            )
        result = run_limited_command(
            [sys.executable, "-m", "compileall", "-q", *python_files],
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
