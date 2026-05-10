from __future__ import annotations

from pathlib import Path

from coding_orchestrator.tools.git import GitCheckpoint, GitManager


class SnapshotManager:
    def __init__(self, repo_path: Path) -> None:
        self.git = GitManager(repo_path)

    def create(self, task_id: str) -> GitCheckpoint:
        return self.git.checkpoint(task_id)

    def rollback(self) -> None:
        self.git.rollback()
