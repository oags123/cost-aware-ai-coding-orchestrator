from __future__ import annotations

from pathlib import Path

from coding_orchestrator.tools.git import GitManager


def current_diff(repo_path: Path) -> str:
    return GitManager(repo_path).diff()


def changed_files(repo_path: Path) -> list[str]:
    return GitManager(repo_path).changed_files()

