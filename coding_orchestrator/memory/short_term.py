from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ShortTermMemory:
    items: list[str] = field(default_factory=list)

    def add(self, item: str) -> None:
        self.items.append(item)

