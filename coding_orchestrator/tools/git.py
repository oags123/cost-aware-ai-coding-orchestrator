from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from coding_orchestrator.schemas import CommandResult
from coding_orchestrator.tools.shell import run_limited_command

GIT_ALLOWLIST = ["git"]


class DirtyWorktreeError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitCheckpoint:
    task_id: str
    tracked_dirty_files: list[str]
    untracked_files: list[str]


class GitManager:
    def __init__(self, repo_path: Path, timeout_seconds: int = 60) -> None:
        self.repo_path = repo_path
        self.timeout_seconds = timeout_seconds

    def status(self) -> CommandResult:
        return run_limited_command(
            ["git", "status", "--short"],
            self.repo_path,
            self.timeout_seconds,
            GIT_ALLOWLIST,
        )

    def branch(self) -> CommandResult:
        return run_limited_command(
            ["git", "branch", "--show-current"],
            self.repo_path,
            self.timeout_seconds,
            GIT_ALLOWLIST,
        )

    def diff(self) -> str:
        result = run_limited_command(
            ["git", "diff", "--"],
            self.repo_path,
            self.timeout_seconds,
            GIT_ALLOWLIST,
        )
        return result.stdout

    def changed_files(self) -> list[str]:
        result = run_limited_command(
            ["git", "diff", "--name-only"],
            self.repo_path,
            self.timeout_seconds,
            GIT_ALLOWLIST,
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def status_entries(self) -> list[tuple[str, str]]:
        result = run_limited_command(
            ["git", "status", "--porcelain"],
            self.repo_path,
            self.timeout_seconds,
            GIT_ALLOWLIST,
        )
        entries: list[tuple[str, str]] = []
        for line in result.stdout.splitlines():
            if not line:
                continue
            entries.append((line[:2], line[3:]))
        return entries

    def dirty_files(self) -> list[str]:
        return [path for status, path in self.status_entries() if status != "??"]

    def untracked_files(self) -> list[str]:
        return [path for status, path in self.status_entries() if status == "??"]

    def checkpoint(self, task_id: str, require_clean: bool = False) -> GitCheckpoint:
        tracked_dirty = self.dirty_files()
        if require_clean and tracked_dirty:
            raise DirtyWorktreeError(
                "worktree has tracked changes before task start: " + ", ".join(tracked_dirty)
            )
        return GitCheckpoint(
            task_id=task_id,
            tracked_dirty_files=tracked_dirty,
            untracked_files=self.untracked_files(),
        )

    def rollback(self) -> CommandResult:
        return run_limited_command(
            ["git", "restore", "--worktree", "--staged", "."],
            self.repo_path,
            self.timeout_seconds,
            GIT_ALLOWLIST,
        )

    def rollback_to_checkpoint(
        self,
        checkpoint: GitCheckpoint,
        preserve_dirs: list[str],
        preserve_files: list[str],
    ) -> CommandResult:
        result = self.rollback()
        if result.returncode != 0:
            return result
        before = set(checkpoint.untracked_files)
        for raw_path in self.untracked_files():
            if raw_path in before or _is_preserved(raw_path, preserve_dirs, preserve_files):
                continue
            path = (self.repo_path / raw_path).resolve()
            try:
                path.relative_to(self.repo_path.resolve())
            except ValueError:
                continue
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        return result

    def commit_task(
        self,
        task_id: str,
        title: str,
        allowed_files: list[str] | None = None,
    ) -> CommandResult:
        status = self.status_entries()
        if not status:
            return CommandResult(
                command=["git", "commit"],
                returncode=0,
                stdout="No changes to commit.",
                stderr="",
            )
        if not allowed_files:
            return CommandResult(
                command=["git", "add"],
                returncode=1,
                stdout="",
                stderr="Refusing to stage changes because task.allowed_files is empty.",
            )
        add_command = ["git", "add", "--", *allowed_files]
        add = run_limited_command(
            add_command,
            self.repo_path,
            self.timeout_seconds,
            GIT_ALLOWLIST,
        )
        if add.returncode != 0:
            return add
        return run_limited_command(
            ["git", "commit", "-m", f"{task_id}: {title}"],
            self.repo_path,
            self.timeout_seconds,
            GIT_ALLOWLIST,
        )


def _is_preserved(path: str, preserve_dirs: list[str], preserve_files: list[str]) -> bool:
    normalized = path.strip("/")
    if normalized in preserve_files:
        return True
    return any(
        normalized == item.strip("/") or normalized.startswith(item.strip("/") + "/")
        for item in preserve_dirs
    )
