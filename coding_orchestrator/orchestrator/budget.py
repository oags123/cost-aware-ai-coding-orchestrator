from __future__ import annotations

from dataclasses import dataclass

from coding_orchestrator.config import BudgetSettings
from coding_orchestrator.schemas import OrchestratorState, TaskSpec


@dataclass
class BudgetGuard:
    settings: BudgetSettings
    project_spend_usd: float = 0.0

    def estimate(self, text: str, output_tokens: int = 1000, rate_per_1k: float = 0.001) -> float:
        input_tokens = max(1, len(text) // 4)
        return ((input_tokens + output_tokens) / 1000.0) * rate_per_1k

    def can_spend(self, task: TaskSpec, state: OrchestratorState) -> bool:
        task_limit = min(task.max_cost_usd, self.settings.max_task_cost_usd)
        project_limit = self.settings.max_project_cost_usd * self.settings.stop_threshold_ratio
        return (
            state.estimated_cost_usd <= task_limit
            and self.project_spend_usd + state.estimated_cost_usd <= project_limit
        )

    def record(self, state: OrchestratorState) -> None:
        self.project_spend_usd += state.estimated_cost_usd

