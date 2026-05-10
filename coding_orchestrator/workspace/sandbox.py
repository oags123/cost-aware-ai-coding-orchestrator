from __future__ import annotations

from pathlib import Path

from coding_orchestrator.orchestrator.policies import is_within_workspace


class WorkspaceSandbox:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()

    def assert_inside(self, path: Path) -> None:
        if not is_within_workspace(path, self.workspace):
            raise PermissionError(f"path outside workspace: {path}")

