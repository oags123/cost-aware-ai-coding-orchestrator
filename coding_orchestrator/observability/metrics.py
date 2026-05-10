from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Metrics:
    completed: int = 0
    failed: int = 0
    escalated: int = 0
    skipped: int = 0
    total_cost_usd: float = 0.0

    def as_dict(self) -> dict[str, int | float]:
        return self.__dict__.copy()

