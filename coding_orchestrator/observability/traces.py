from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Trace:
    request_id: str
    steps: list[str] = field(default_factory=list)

    def add(self, step: str) -> None:
        self.steps.append(step)

