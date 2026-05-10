from __future__ import annotations

from pathlib import Path

from coding_orchestrator.orchestrator.policies import is_forbidden_path, is_within_workspace
from coding_orchestrator.schemas import ValidationResult


class PermissionValidator:
    name = "permission"

    def __init__(
        self,
        paths: list[str],
        workspace: Path,
        allowed_files: list[str],
        forbidden_paths: list[str],
    ) -> None:
        self.paths = paths
        self.workspace = workspace
        self.allowed_files = allowed_files
        self.forbidden_paths = forbidden_paths

    def validate(self) -> ValidationResult:
        errors: list[str] = []
        allowed = set(self.allowed_files)
        for raw_path in self.paths:
            candidate = (self.workspace / raw_path).resolve()
            if is_forbidden_path(raw_path, self.forbidden_paths):
                errors.append(f"forbidden path: {raw_path}")
            if not is_within_workspace(candidate, self.workspace):
                errors.append(f"path escapes workspace: {raw_path}")
            if allowed and raw_path not in allowed:
                errors.append(f"path not allowed by task: {raw_path}")
        return ValidationResult(name=self.name, passed=not errors, message="; ".join(errors))

