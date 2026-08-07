from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from coding_orchestrator.schemas import CommandResult
from coding_orchestrator.tools.shell import run_limited_command

GIT_ALLOWLIST = ["git"]


class DirtyWorktreeError(RuntimeError):
    pass


class GitOperationError(RuntimeError):
    pass


class HeadChangedError(RuntimeError):
    """Raised when HEAD moved unexpectedly between checkpoint and commit/apply."""


@dataclass(frozen=True)
class GitCheckpoint:
    task_id: str
    head_sha: str
    stashed: bool
    tracked_dirty_files: list[str]
    untracked_files: list[str]


class GitManager:
    def __init__(self, repo_path: Path, timeout_seconds: int = 60) -> None:
        self.repo_path = repo_path
        self.timeout_seconds = timeout_seconds

    def _run(self, args: list[str], stdin: str | None = None) -> CommandResult:
        return run_limited_command(
            args,
            self.repo_path,
            self.timeout_seconds,
            GIT_ALLOWLIST,
            stdin=stdin,
        )

    def status(self) -> CommandResult:
        return self._run(["git", "status", "--short"])

    def branch(self) -> CommandResult:
        return self._run(["git", "branch", "--show-current"])

    def diff(self) -> str:
        return self._run(["git", "diff", "--"]).stdout

    def head_sha(self) -> str:
        result = self._run(["git", "rev-parse", "HEAD"])
        if result.returncode != 0:
            raise GitOperationError(
                "unable to resolve HEAD (not a git repository or no commits yet): "
                + (result.stderr or result.stdout)
            )
        return result.stdout.strip()

    def status_entries(self) -> list[tuple[str, str]]:
        """Return (status, path) pairs from `git status --porcelain=v1 -z --untracked-files=all`.

        Uses NUL-separated, unquoted output so paths containing spaces or other
        unusual characters are parsed correctly, and renames are represented as
        their post-rename path (the pre-rename path is consumed and discarded).
        `--untracked-files=all` forces git to list every file inside a newly
        untracked directory individually instead of collapsing it to `dir/` --
        without this, per-file forbidden-path/allowed-file checks could be silently
        bypassed for files inside a brand-new directory the builder's patch creates.
        """
        result = self._run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"]
        )
        if result.returncode != 0:
            raise GitOperationError(
                "git status failed (not a git repository?): " + (result.stderr or result.stdout)
            )
        tokens = result.stdout.split("\0")
        entries: list[tuple[str, str]] = []
        i = 0
        while i < len(tokens):
            token = tokens[i]
            if not token:
                i += 1
                continue
            status = token[:2]
            path = token[3:]
            entries.append((status, path))
            if status[0] in {"R", "C"}:
                # Rename/copy records carry an extra NUL-terminated original path.
                i += 2
            else:
                i += 1
        return entries

    def changed_files(self) -> list[str]:
        """All paths with a working-tree difference from HEAD: tracked modifications,
        staged changes, untracked files, deletions, and renames (post-rename path).
        """
        seen: list[str] = []
        for status, path in self.status_entries():
            if status == "!!":
                continue
            if path not in seen:
                seen.append(path)
        return seen

    def dirty_files(self) -> list[str]:
        return [path for status, path in self.status_entries() if status != "??" and status != "!!"]

    def untracked_files(self) -> list[str]:
        return [path for status, path in self.status_entries() if status == "??"]

    def checkpoint(
        self,
        task_id: str,
        require_clean: bool = False,
        preserve_dirs: list[str] | None = None,
        preserve_files: list[str] | None = None,
    ) -> GitCheckpoint:
        """Snapshot the current HEAD and stash away any pre-existing dirty/untracked
        state so the task starts from a clean tree. `preserve_dirs`/`preserve_files`
        (the orchestrator's own runtime data: logs, ledger, caches) are excluded from
        the stash via pathspec so they are never swept up regardless of whether the
        target repository's own .gitignore happens to cover them.
        """
        tracked_dirty = self.dirty_files()
        untracked = self.untracked_files()
        if require_clean and tracked_dirty:
            raise DirtyWorktreeError(
                "worktree has tracked changes before task start: " + ", ".join(tracked_dirty)
            )
        head_sha = self.head_sha()
        stashed = False
        if tracked_dirty or untracked:
            excludes = [
                f":!{item.strip('/')}" for item in (*(preserve_dirs or []), *(preserve_files or []))
            ]
            stash = self._run(
                [
                    "git",
                    "stash",
                    "push",
                    "--include-untracked",
                    "-m",
                    f"orchestrator-{task_id}",
                    "--",
                    ".",
                    *excludes,
                ]
            )
            if stash.returncode != 0:
                raise GitOperationError(
                    "failed to checkpoint pre-existing worktree state: "
                    + (stash.stderr or stash.stdout)
                )
            stashed = "No local changes to save" not in stash.stdout
        return GitCheckpoint(
            task_id=task_id,
            head_sha=head_sha,
            stashed=stashed,
            tracked_dirty_files=tracked_dirty,
            untracked_files=untracked,
        )

    def verify_head(self, checkpoint: GitCheckpoint) -> None:
        current = self.head_sha()
        if current != checkpoint.head_sha:
            raise HeadChangedError(
                f"repository HEAD changed during task execution "
                f"(expected {checkpoint.head_sha}, found {current}); "
                "refusing to apply or commit"
            )

    def rollback_to_checkpoint(
        self,
        checkpoint: GitCheckpoint,
        preserve_dirs: list[str],
        preserve_files: list[str],
    ) -> CommandResult:
        """Discard everything the task did and restore the exact pre-task state,
        including any pre-existing uncommitted work that was stashed at checkpoint time.
        """
        reset = self._run(["git", "reset", "--hard", checkpoint.head_sha])
        if reset.returncode != 0:
            return reset
        clean_command = ["git", "clean", "-fd"]
        for item in (*preserve_dirs, *preserve_files):
            clean_command.extend(["-e", item.strip("/")])
        clean = self._run(clean_command)
        if clean.returncode != 0:
            return clean
        if checkpoint.stashed:
            pop = self._run(["git", "stash", "pop"])
            return pop
        return clean

    def restore_pending_work(self, checkpoint: GitCheckpoint) -> CommandResult:
        """After a successful commit, reapply any pre-existing stashed work on top."""
        if not checkpoint.stashed:
            return CommandResult(
                command=["git", "stash", "pop"],
                returncode=0,
                stdout="nothing stashed",
                stderr="",
            )
        return self._run(["git", "stash", "pop"])

    def commit_task(
        self,
        task_id: str,
        title: str,
        changed_files: list[str],
        allowed_files: list[str] | None = None,
    ) -> CommandResult:
        if not changed_files:
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
        to_stage = sorted(set(changed_files) & set(allowed_files))
        if not to_stage:
            return CommandResult(
                command=["git", "add"],
                returncode=1,
                stdout="",
                stderr=(
                    "Refusing to commit: changed files are outside task.allowed_files boundary "
                    f"(changed={sorted(changed_files)}, allowed={sorted(allowed_files)})."
                ),
            )
        add = self._run(["git", "add", "--", *to_stage])
        if add.returncode != 0:
            return add
        return self._run(["git", "commit", "-m", f"{task_id}: {title}"])
