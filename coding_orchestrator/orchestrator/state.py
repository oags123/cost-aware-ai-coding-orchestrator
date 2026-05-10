from __future__ import annotations

import json
from pathlib import Path

from coding_orchestrator.schemas import OrchestratorState


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, state: OrchestratorState) -> None:
        states = self.load_all()
        states[state.request_id] = state
        payload = {key: value.model_dump(mode="json") for key, value in states.items()}
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def load_all(self) -> dict[str, OrchestratorState]:
        if not self.path.exists():
            return {}
        loaded = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            return {}
        return {key: OrchestratorState.model_validate(value) for key, value in loaded.items()}

