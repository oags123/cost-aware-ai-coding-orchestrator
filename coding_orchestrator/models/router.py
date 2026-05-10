from __future__ import annotations

from coding_orchestrator.config import ModelRoutingSettings
from coding_orchestrator.schemas import Complexity, RiskLevel


class ModelRouter:
    def __init__(self, settings: ModelRoutingSettings | None = None) -> None:
        self.settings = settings or ModelRoutingSettings()

    def select_model(self, complexity: Complexity, risk: RiskLevel) -> str:
        if risk == "high" or complexity == "critical":
            return "human-approval" if complexity == "critical" else self.settings.hard
        routes = self.settings.model_dump()
        return str(routes[complexity])
