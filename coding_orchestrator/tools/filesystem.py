from __future__ import annotations

from pathlib import Path

from coding_orchestrator.orchestrator.policies import is_forbidden_path, is_within_workspace


class FileBoundaryError(ValueError):
    pass


class FileSystem:
    def __init__(self, workspace: Path, forbidden_paths: list[str] | None = None) -> None:
        self.workspace = workspace.resolve()
        self.forbidden_paths = forbidden_paths

    def resolve_safe(self, relative_path: str) -> Path:
        if is_forbidden_path(relative_path, self.forbidden_paths):
            raise FileBoundaryError(f"Forbidden path: {relative_path}")
        path = (self.workspace / relative_path).resolve()
        if not is_within_workspace(path, self.workspace):
            raise FileBoundaryError(f"Path escapes workspace: {relative_path}")
        return path

    def read_file(self, relative_path: str) -> str:
        return self.resolve_safe(relative_path).read_text(encoding="utf-8")

    def write_file(self, relative_path: str, content: str, allowed_files: list[str]) -> None:
        if relative_path not in allowed_files:
            raise FileBoundaryError(f"File not allowed: {relative_path}")
        path = self.resolve_safe(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def list_files(self) -> list[str]:
        return [
            str(path.relative_to(self.workspace))
            for path in self.workspace.rglob("*")
            if path.is_file() and ".git" not in path.parts
        ]

