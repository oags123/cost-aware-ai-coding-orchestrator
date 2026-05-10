from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from coding_orchestrator.config import BudgetSettings, ModelPricing, PricingSettings
from coding_orchestrator.schemas import OrchestratorState, TaskSpec


class BudgetExceeded(RuntimeError):
    pass


class BudgetEstimate(BaseModel):
    project_id: str
    task_id: str | None
    attempt_id: int
    model_role: str
    provider: str
    model: str
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_input_cost_usd: float
    estimated_output_cost_usd: float
    estimated_total_cost_usd: float
    status: str = "estimated"


class BudgetUsage(BaseModel):
    project_id: str
    project_total_budget_usd: float
    project_total_spend_usd: float
    project_total_remaining_usd: float
    cheap_builder_budget_usd: float
    cheap_builder_spend_usd: float
    cheap_builder_remaining_usd: float
    expensive_reviewer_budget_usd: float
    expensive_reviewer_spend_usd: float
    expensive_reviewer_remaining_usd: float
    emergency_budget_usd: float
    emergency_spend_usd: float
    emergency_remaining_usd: float
    blocked_calls: int


class BudgetLedger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def record(
        self,
        estimate: BudgetEstimate,
        *,
        actual_input_tokens: int | None = None,
        actual_output_tokens: int | None = None,
        actual_cost_usd: float | None = None,
        status: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO budget_events (
                    project_id, task_id, attempt_id, model_role, provider, model,
                    estimated_input_tokens, estimated_output_tokens,
                    estimated_input_cost_usd, estimated_output_cost_usd,
                    estimated_total_cost_usd, actual_input_tokens, actual_output_tokens,
                    actual_cost_usd, timestamp, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    estimate.project_id,
                    estimate.task_id,
                    estimate.attempt_id,
                    estimate.model_role,
                    estimate.provider,
                    estimate.model,
                    estimate.estimated_input_tokens,
                    estimate.estimated_output_tokens,
                    estimate.estimated_input_cost_usd,
                    estimate.estimated_output_cost_usd,
                    estimate.estimated_total_cost_usd,
                    actual_input_tokens,
                    actual_output_tokens,
                    actual_cost_usd,
                    datetime.now(UTC).isoformat(),
                    status or estimate.status,
                ),
            )

    def spend_for_project(self, project_id: str) -> float:
        return self._sum("project_id = ? AND status != 'blocked'", (project_id,))

    def spend_for_role(self, project_id: str, model_role: str) -> float:
        return self._sum(
            "project_id = ? AND model_role = ? AND status != 'blocked'",
            (project_id, model_role),
        )

    def spend_for_task(self, project_id: str, task_id: str | None) -> float:
        if task_id is None:
            return self._sum(
                "project_id = ? AND task_id IS NULL AND status != 'blocked'",
                (project_id,),
            )
        return self._sum(
            "project_id = ? AND task_id = ? AND status != 'blocked'",
            (project_id, task_id),
        )

    def blocked_calls(self, project_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM budget_events WHERE project_id = ? AND status = 'blocked'",
                (project_id,),
            ).fetchone()
        return int(row[0]) if row else 0

    def usage(self, settings: BudgetSettings) -> BudgetUsage:
        project_spend = self.spend_for_project(settings.project_id)
        cheap_spend = self.spend_for_role(settings.project_id, "cheap_builder")
        expensive_spend = self.spend_for_role(settings.project_id, "expensive_reviewer")
        emergency_spend = self.spend_for_role(settings.project_id, "emergency")
        return BudgetUsage(
            project_id=settings.project_id,
            project_total_budget_usd=settings.project_total_budget_usd,
            project_total_spend_usd=project_spend,
            project_total_remaining_usd=settings.project_total_budget_usd - project_spend,
            cheap_builder_budget_usd=settings.cheap_builder_budget_usd,
            cheap_builder_spend_usd=cheap_spend,
            cheap_builder_remaining_usd=settings.cheap_builder_budget_usd - cheap_spend,
            expensive_reviewer_budget_usd=settings.expensive_reviewer_budget_usd,
            expensive_reviewer_spend_usd=expensive_spend,
            expensive_reviewer_remaining_usd=settings.expensive_reviewer_budget_usd
            - expensive_spend,
            emergency_budget_usd=settings.emergency_budget_usd,
            emergency_spend_usd=emergency_spend,
            emergency_remaining_usd=settings.emergency_budget_usd - emergency_spend,
            blocked_calls=self.blocked_calls(settings.project_id),
        )

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS budget_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL,
                    task_id TEXT,
                    attempt_id INTEGER NOT NULL,
                    model_role TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    estimated_input_tokens INTEGER NOT NULL,
                    estimated_output_tokens INTEGER NOT NULL,
                    estimated_input_cost_usd REAL NOT NULL,
                    estimated_output_cost_usd REAL NOT NULL,
                    estimated_total_cost_usd REAL NOT NULL,
                    actual_input_tokens INTEGER,
                    actual_output_tokens INTEGER,
                    actual_cost_usd REAL,
                    timestamp TEXT NOT NULL,
                    status TEXT NOT NULL
                )
                """
            )

    def _sum(self, where_clause: str, params: tuple[str, ...]) -> float:
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT COALESCE(SUM(COALESCE(actual_cost_usd, estimated_total_cost_usd)), 0)
                FROM budget_events
                WHERE {where_clause}
                """,
                params,
            ).fetchone()
        return float(row[0]) if row else 0.0

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)


@dataclass
class BudgetGuard:
    settings: BudgetSettings
    pricing: PricingSettings | None = None
    ledger: BudgetLedger | None = None
    project_spend_usd: float = 0.0

    def __post_init__(self) -> None:
        if self.ledger is None:
            self.ledger = BudgetLedger(Path(self.settings.ledger_path))
        if self.pricing is None:
            self.pricing = PricingSettings()

    def estimate(self, text: str, output_tokens: int = 1000, rate_per_1k: float = 0.001) -> float:
        input_tokens = self.estimate_tokens(text)
        return ((input_tokens + output_tokens) / 1000.0) * rate_per_1k

    def estimate_pre_call(
        self,
        *,
        task: TaskSpec,
        attempt_id: int,
        model_role: str,
        context: str,
        model_override: str | None = None,
    ) -> BudgetEstimate:
        pricing = self._pricing_for_role(model_role)
        input_tokens = self.estimate_tokens(context)
        output_tokens = pricing.max_output_tokens
        input_cost = (input_tokens / 1_000_000.0) * pricing.input_usd_per_1m_tokens
        output_cost = (output_tokens / 1_000_000.0) * pricing.output_usd_per_1m_tokens
        return BudgetEstimate(
            project_id=self.settings.project_id,
            task_id=task.id,
            attempt_id=attempt_id,
            model_role=model_role,
            provider=pricing.provider,
            model=model_override or pricing.model,
            estimated_input_tokens=input_tokens,
            estimated_output_tokens=output_tokens,
            estimated_input_cost_usd=input_cost,
            estimated_output_cost_usd=output_cost,
            estimated_total_cost_usd=input_cost + output_cost,
        )

    def check_pre_call(self, task: TaskSpec, estimate: BudgetEstimate) -> None:
        assert self.ledger is not None
        failures: list[str] = []
        project_spend = self.ledger.spend_for_project(estimate.project_id)
        role_spend = self.ledger.spend_for_role(estimate.project_id, estimate.model_role)
        task_spend = self.ledger.spend_for_task(estimate.project_id, estimate.task_id)

        task_limit = min(task.max_cost_usd, self.settings.max_task_cost_usd)
        if estimate.estimated_total_cost_usd > task_limit:
            failures.append("task budget")
        if task_spend + estimate.estimated_total_cost_usd > task.max_cost_usd:
            failures.append("task cumulative budget")
        projected_project_spend = project_spend + estimate.estimated_total_cost_usd
        if projected_project_spend > self.settings.project_total_budget_usd:
            failures.append("project_total budget")
        role_budget = self._role_budget(estimate.model_role)
        if role_spend + estimate.estimated_total_cost_usd > role_budget:
            failures.append(f"{estimate.model_role} budget")

        if failures:
            self.ledger.record(estimate, status="blocked")
            raise BudgetExceeded("Pre-call budget estimate exceeds " + ", ".join(failures))

    def record_estimate(self, estimate: BudgetEstimate, status: str = "estimated") -> None:
        assert self.ledger is not None
        self.ledger.record(estimate, status=status)

    def report(self) -> BudgetUsage:
        assert self.ledger is not None
        return self.ledger.usage(self.settings)

    def can_spend(self, task: TaskSpec, state: OrchestratorState) -> bool:
        assert self.ledger is not None
        task_limit = min(task.max_cost_usd, self.settings.max_task_cost_usd)
        project_limit = self.settings.project_total_budget_usd * self.settings.stop_threshold_ratio
        project_spend = self.ledger.spend_for_project(self.settings.project_id)
        return (
            state.estimated_cost_usd <= task_limit
            and project_spend + state.estimated_cost_usd <= project_limit
        )

    def record(self, state: OrchestratorState) -> None:
        self.project_spend_usd += state.estimated_cost_usd

    def estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def _pricing_for_role(self, model_role: str) -> ModelPricing:
        assert self.pricing is not None
        pricing = self.pricing.roles.get(model_role)
        if pricing is None:
            raise BudgetExceeded(f"No pricing configured for model role: {model_role}")
        return pricing

    def _role_budget(self, model_role: str) -> float:
        if model_role == "cheap_builder":
            return self.settings.cheap_builder_budget_usd
        if model_role == "expensive_reviewer":
            return self.settings.expensive_reviewer_budget_usd
        if model_role == "emergency":
            return self.settings.emergency_budget_usd
        return self.settings.project_total_budget_usd
