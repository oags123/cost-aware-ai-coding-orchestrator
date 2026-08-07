from __future__ import annotations

import fcntl
import os
from pathlib import Path
from types import TracebackType


class ConcurrentExecutionError(RuntimeError):
    pass


class RepoLock:
    """Advisory, process-safe lock preventing concurrent orchestrator runs against
    the same repository. Uses flock so the OS releases the lock automatically if the
    holding process crashes.
    """

    def __init__(self, repo_path: Path) -> None:
        self.lock_path = repo_path / ".orchestrator.lock"
        self._fd: int | None = None

    def __enter__(self) -> RepoLock:
        self._fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(self._fd)
            self._fd = None
            raise ConcurrentExecutionError(
                f"another orchestrator run holds the lock on {self.lock_path}"
            ) from exc
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None
