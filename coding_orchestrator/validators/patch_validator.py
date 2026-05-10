from __future__ import annotations

from pathlib import Path

from coding_orchestrator.config import ValidationSettings
from coding_orchestrator.schemas import ValidationResult
from coding_orchestrator.validators.permission_validator import PermissionValidator


class PatchValidator:
    name = "patch"

    def __init__(
        self,
        changed_files: list[str],
        workspace: Path,
        allowed_files: list[str],
        settings: ValidationSettings,
    ) -> None:
        self.changed_files = changed_files
        self.workspace = workspace
        self.allowed_files = allowed_files
        self.settings = settings

    def validate(self) -> ValidationResult:
        if len(self.changed_files) > self.settings.max_files_changed:
            return ValidationResult(
                name=self.name,
                passed=False,
                message=f"too many files changed: {len(self.changed_files)}",
                details={"changed_files": self.changed_files},
            )
        permission = PermissionValidator(
            self.changed_files,
            self.workspace,
            self.allowed_files,
            self.settings.forbidden_paths,
        ).validate()
        if not permission.passed:
            return ValidationResult(
                name=self.name,
                passed=False,
                message=permission.message,
                details={"changed_files": self.changed_files},
            )
        return ValidationResult(
            name=self.name,
            passed=True,
            message="patch within boundaries",
            details={"changed_files": self.changed_files},
        )

