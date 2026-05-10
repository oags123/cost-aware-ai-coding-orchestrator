from __future__ import annotations

import json
from pathlib import Path


class ProjectFacts:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        loaded = json.loads(self.path.read_text(encoding="utf-8"))
        return {str(key): str(value) for key, value in loaded.items()}

    def save(self, facts: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(facts, sort_keys=True, indent=2), encoding="utf-8")

