from __future__ import annotations

from coding_orchestrator.orchestrator.policies import command_is_allowlisted
from coding_orchestrator.schemas import ValidationResult


class CommandSafetyValidator:
    name = "command_safety"

    def __init__(self, commands: list[str], allowlist: list[str]) -> None:
        self.commands = commands
        self.allowlist = allowlist

    def validate(self) -> ValidationResult:
        unsafe = [cmd for cmd in self.commands if not command_is_allowlisted(cmd, self.allowlist)]
        return ValidationResult(
            name=self.name,
            passed=not unsafe,
            message="; ".join(f"not allowlisted: {cmd}" for cmd in unsafe),
            details={"commands": self.commands},
        )

