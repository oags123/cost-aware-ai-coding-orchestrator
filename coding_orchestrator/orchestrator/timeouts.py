from __future__ import annotations

from dataclasses import dataclass
from time import monotonic


class TimeoutExceeded(RuntimeError):
    """Raised when a bounded workflow exceeds its runtime budget."""


@dataclass
class TimeoutGuard:
    max_seconds: float
    started_at: float = 0.0

    def __post_init__(self) -> None:
        self.started_at = monotonic()

    @property
    def elapsed(self) -> float:
        return monotonic() - self.started_at

    def remaining(self) -> float:
        return max(0.0, self.max_seconds - self.elapsed)

    def check(self) -> None:
        if self.elapsed > self.max_seconds:
            raise TimeoutExceeded(f"Runtime exceeded {self.max_seconds} seconds")

