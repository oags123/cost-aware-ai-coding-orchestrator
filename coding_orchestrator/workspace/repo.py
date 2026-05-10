from __future__ import annotations

from pathlib import Path


class WorkspaceRepo:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()

    def ensure_exists(self) -> Path:
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        return self.path

