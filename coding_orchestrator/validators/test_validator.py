from __future__ import annotations

from pathlib import Path

from coding_orchestrator.schemas import ValidationResult
from coding_orchestrator.tools.test_runner import run_validation_command


class TestValidator:
    __test__ = False
    name = "tests"

    def __init__(self, commands: list[str], cwd: Path, timeout_seconds: int) -> None:
        self.commands = commands
        self.cwd = cwd
        self.timeout_seconds = timeout_seconds

    def validate(self) -> ValidationResult:
        failures: list[str] = []
        details: dict[str, dict[str, str | int | bool]] = {}
        for command in self.commands:
            result = run_validation_command(command, self.cwd, self.timeout_seconds)
            details[command] = {
                "returncode": result.returncode,
                "stdout": result.stdout[-4000:],
                "stderr": result.stderr[-4000:],
                "timed_out": result.timed_out,
            }
            if result.returncode != 0:
                failures.append(command)
        message = "failed commands: " + ", ".join(failures) if failures else "all commands passed"
        return ValidationResult(
            name=self.name,
            passed=not failures,
            message=message,
            details=details,
        )
