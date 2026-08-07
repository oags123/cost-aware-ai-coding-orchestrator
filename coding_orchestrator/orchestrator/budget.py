from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from coding_orchestrator.config import BudgetSettings, ModelPricing, PricingSettings
from coding_orchestrator.models.provider import ModelUsage
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
    inference_tier: str | None = None
    estimated_context_chars: int = 0
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
    role_budget_limits_usd: dict[str, float] = Field(default_factory=dict)
    role_spend_usd: dict[str, float] = Field(default_factory=dict)
    role_remaining_usd: dict[str, float] = Field(default_factory=dict)
    blocked_calls: int
    limit_failures: dict[str, int] = Field(default_factory=dict)
    largest_context_chars: int = 0
    largest_input_tokens: int = 0
    largest_patch_bytes: int = 0
    largest_stdout_bytes: int = 0
    largest_stderr_bytes: int = 0
    largest_validation_output_bytes: int = 0
    calls_by_service_tier: dict[str, int] = Field(default_factory=dict)
    estimated_cost_by_service_tier_usd: dict[str, float] = Field(default_factory=dict)
    service_tier_timeouts: dict[str, int] = Field(default_factory=dict)
    service_tier_fallbacks: int = 0


class TierUsage(BaseModel):
    calls_by_service_tier: dict[str, int] = Field(default_factory=dict)
    estimated_cost_by_service_tier_usd: dict[str, float] = Field(default_factory=dict)
    service_tier_fallbacks: int = 0


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
                    inference_tier,
                    estimated_context_chars,
                    estimated_input_tokens, estimated_output_tokens,
                    estimated_input_cost_usd, estimated_output_cost_usd,
                    estimated_total_cost_usd, actual_input_tokens, actual_output_tokens,
                    actual_cost_usd, timestamp, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    estimate.project_id,
                    estimate.task_id,
                    estimate.attempt_id,
                    estimate.model_role,
                    estimate.provider,
                    estimate.model,
                    estimate.inference_tier,
                    estimate.estimated_context_chars,
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

    def record_actual_usage(
        self,
        *,
        project_id: str,
        task_id: str | None,
        attempt_id: int,
        model_role: str,
        actual_input_tokens: int,
        actual_output_tokens: int,
        actual_cost_usd: float,
        status: str = "completed",
        requested_service_tier: str | None = None,
        actual_service_tier: str | None = None,
        fallback_occurred: bool = False,
    ) -> None:
        """Idempotently true-up the most recent un-reconciled estimate row for this
        call with real provider usage. Updates in place (never inserts a new row) so
        actual spend is never double-counted alongside its originating estimate.

        `requested_service_tier`/`actual_service_tier` record exactly what tier was
        asked for versus what the provider reported back, and `fallback_occurred` is
        always False under the strict Flex-only policy (there is no automatic
        fallback mechanism left to set it) -- its presence lets a ledger reader
        positively confirm no fallback ever happened, rather than merely assuming it.
        """
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM budget_events
                WHERE project_id = ? AND attempt_id = ? AND model_role = ?
                  AND (task_id = ? OR (task_id IS NULL AND ? IS NULL))
                  AND actual_cost_usd IS NULL
                ORDER BY id DESC LIMIT 1
                """,
                (project_id, attempt_id, model_role, task_id, task_id),
            ).fetchone()
            if row is None:
                return
            conn.execute(
                """
                UPDATE budget_events
                SET actual_input_tokens = ?, actual_output_tokens = ?,
                    actual_cost_usd = ?, status = ?,
                    requested_service_tier = ?, actual_service_tier = ?,
                    fallback_occurred = ?
                WHERE id = ?
                """,
                (
                    actual_input_tokens,
                    actual_output_tokens,
                    actual_cost_usd,
                    status,
                    requested_service_tier,
                    actual_service_tier,
                    int(fallback_occurred),
                    row[0],
                ),
            )

    def spend_for_project(self, project_id: str) -> float:
        return self._sum(
            "project_id = ? AND status != 'blocked' AND status NOT LIKE '%_limit_exceeded'",
            (project_id,),
        )

    def spend_for_role(self, project_id: str, model_role: str) -> float:
        return self._sum(
            "project_id = ? AND model_role = ? AND status != 'blocked' "
            "AND status NOT LIKE '%_limit_exceeded'",
            (project_id, model_role),
        )

    def spend_for_task(self, project_id: str, task_id: str | None) -> float:
        if task_id is None:
            return self._sum(
                "project_id = ? AND task_id IS NULL AND status != 'blocked' "
                "AND status NOT LIKE '%_limit_exceeded'",
                (project_id,),
            )
        return self._sum(
            "project_id = ? AND task_id = ? AND status != 'blocked' "
            "AND status NOT LIKE '%_limit_exceeded'",
            (project_id, task_id),
        )

    def blocked_calls(self, project_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) FROM budget_events
                WHERE project_id = ?
                  AND (status = 'blocked' OR status LIKE '%_limit_exceeded')
                """,
                (project_id,),
            ).fetchone()
        return int(row[0]) if row else 0

    def usage(
        self,
        settings: BudgetSettings,
        *,
        limit_failures: dict[str, int] | None = None,
        largest_patch_bytes: int = 0,
        largest_stdout_bytes: int = 0,
        largest_stderr_bytes: int = 0,
        largest_validation_output_bytes: int = 0,
        service_tier_timeouts: dict[str, int] | None = None,
        service_tier_fallbacks: int = 0,
    ) -> BudgetUsage:
        project_spend = self.spend_for_project(settings.project_id)
        largest = self._largest_estimates(settings.project_id)
        ledger_limit_failures = self.limit_failures(settings.project_id)
        combined_limit_failures = dict(ledger_limit_failures)
        for key, count in (limit_failures or {}).items():
            combined_limit_failures[key] = max(combined_limit_failures.get(key, 0), count)
        tier_usage = self.tier_usage(settings.project_id)
        role_spend = {
            role_name: self.spend_for_role(settings.project_id, role_name)
            for role_name in settings.role_budgets_usd
        }
        role_remaining = {
            role_name: settings.role_budgets_usd[role_name] - role_spend.get(role_name, 0.0)
            for role_name in settings.role_budgets_usd
        }
        timeout_counts = dict(tier_usage.calls_by_service_tier)
        timeout_counts.clear()
        timeout_counts.update(service_tier_timeouts or {})
        return BudgetUsage(
            project_id=settings.project_id,
            project_total_budget_usd=settings.project_total_budget_usd,
            project_total_spend_usd=project_spend,
            project_total_remaining_usd=settings.project_total_budget_usd - project_spend,
            role_budget_limits_usd=dict(settings.role_budgets_usd),
            role_spend_usd=role_spend,
            role_remaining_usd=role_remaining,
            blocked_calls=self.blocked_calls(settings.project_id),
            limit_failures=combined_limit_failures,
            largest_context_chars=largest["context_chars"],
            largest_input_tokens=largest["input_tokens"],
            largest_patch_bytes=largest_patch_bytes,
            largest_stdout_bytes=largest_stdout_bytes,
            largest_stderr_bytes=largest_stderr_bytes,
            largest_validation_output_bytes=largest_validation_output_bytes,
            calls_by_service_tier=tier_usage.calls_by_service_tier,
            estimated_cost_by_service_tier_usd=tier_usage.estimated_cost_by_service_tier_usd,
            service_tier_timeouts=timeout_counts,
            service_tier_fallbacks=max(
                service_tier_fallbacks,
                tier_usage.service_tier_fallbacks,
            ),
        )

    def tier_usage(self, project_id: str) -> TierUsage:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    COALESCE(inference_tier, 'unspecified'),
                    COUNT(*),
                    COALESCE(SUM(estimated_total_cost_usd), 0)
                FROM budget_events
                WHERE project_id = ?
                  AND status != 'blocked'
                  AND status NOT LIKE '%_limit_exceeded'
                GROUP BY COALESCE(inference_tier, 'unspecified')
                """,
                (project_id,),
            ).fetchall()
        calls_by_service_tier: dict[str, int] = {}
        cost_by_service_tier: dict[str, float] = {}
        for tier, calls, cost in rows:
            calls_by_service_tier[str(tier)] = int(calls)
            cost_by_service_tier[str(tier)] = float(cost)
        return TierUsage(
            calls_by_service_tier=calls_by_service_tier,
            estimated_cost_by_service_tier_usd=cost_by_service_tier,
            service_tier_fallbacks=calls_by_service_tier.get("standard", 0),
        )

    def limit_failures(self, project_id: str) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT status, COUNT(*)
                FROM budget_events
                WHERE project_id = ? AND status LIKE '%_limit_exceeded'
                GROUP BY status
                """,
                (project_id,),
            ).fetchall()
        return {str(status): int(count) for status, count in rows}

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
                    inference_tier TEXT,
                    estimated_context_chars INTEGER NOT NULL DEFAULT 0,
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
            columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(budget_events)").fetchall()
            }
            if "estimated_context_chars" not in columns:
                conn.execute(
                    "ALTER TABLE budget_events ADD COLUMN estimated_context_chars INTEGER "
                    "NOT NULL DEFAULT 0"
                )
            if "inference_tier" not in columns:
                conn.execute("ALTER TABLE budget_events ADD COLUMN inference_tier TEXT")
            if "requested_service_tier" not in columns:
                conn.execute(
                    "ALTER TABLE budget_events ADD COLUMN requested_service_tier TEXT"
                )
            if "actual_service_tier" not in columns:
                conn.execute("ALTER TABLE budget_events ADD COLUMN actual_service_tier TEXT")
            if "fallback_occurred" not in columns:
                conn.execute(
                    "ALTER TABLE budget_events ADD COLUMN fallback_occurred "
                    "INTEGER NOT NULL DEFAULT 0"
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

    def _largest_estimates(self, project_id: str) -> dict[str, int]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COALESCE(MAX(estimated_context_chars), 0),
                    COALESCE(MAX(estimated_input_tokens), 0)
                FROM budget_events
                WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()
        return {
            "context_chars": int(row[0]) if row else 0,
            "input_tokens": int(row[1]) if row else 0,
        }


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
        inference_tier: str | None = None,
        max_output_tokens_override: int | None = None,
    ) -> BudgetEstimate:
        pricing = self.pricing_for_role(model_role, inference_tier)
        input_tokens = self.estimate_tokens(context)
        output_tokens = pricing.max_output_tokens
        if max_output_tokens_override is not None:
            output_tokens = min(output_tokens, max_output_tokens_override)
        input_cost = (input_tokens / 1_000_000.0) * pricing.input_usd_per_1m_tokens
        output_cost = (output_tokens / 1_000_000.0) * pricing.output_usd_per_1m_tokens
        return BudgetEstimate(
            project_id=self.settings.project_id,
            task_id=task.id,
            attempt_id=attempt_id,
            model_role=model_role,
            provider=pricing.provider,
            model=model_override or pricing.model,
            inference_tier=inference_tier or pricing.inference_tier,
            estimated_context_chars=len(context),
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

    def record_actual(
        self,
        estimate: BudgetEstimate,
        usage: ModelUsage,
        status: str = "completed",
        *,
        requested_service_tier: str | None = None,
        actual_service_tier: str | None = None,
        fallback_occurred: bool = False,
    ) -> None:
        """Reconcile real provider token usage/cost into the ledger for the call
        this estimate was made for. Safe to call at most once per attempt; a repeat
        call for an already-reconciled attempt is a no-op (see record_actual_usage).
        """
        assert self.ledger is not None
        pricing = self.pricing_for_role(estimate.model_role, estimate.inference_tier)
        input_cost = (usage.input_tokens / 1_000_000.0) * pricing.input_usd_per_1m_tokens
        output_cost = (usage.output_tokens / 1_000_000.0) * pricing.output_usd_per_1m_tokens
        self.ledger.record_actual_usage(
            project_id=estimate.project_id,
            task_id=estimate.task_id,
            attempt_id=estimate.attempt_id,
            model_role=estimate.model_role,
            actual_input_tokens=usage.input_tokens,
            actual_output_tokens=usage.output_tokens,
            actual_cost_usd=input_cost + output_cost,
            status=status,
            requested_service_tier=requested_service_tier,
            actual_service_tier=actual_service_tier,
            fallback_occurred=fallback_occurred,
        )

    def report(
        self,
        *,
        limit_failures: dict[str, int] | None = None,
        largest_patch_bytes: int = 0,
        largest_stdout_bytes: int = 0,
        largest_stderr_bytes: int = 0,
        largest_validation_output_bytes: int = 0,
        service_tier_timeouts: dict[str, int] | None = None,
        service_tier_fallbacks: int = 0,
    ) -> BudgetUsage:
        assert self.ledger is not None
        return self.ledger.usage(
            self.settings,
            limit_failures=limit_failures,
            largest_patch_bytes=largest_patch_bytes,
            largest_stdout_bytes=largest_stdout_bytes,
            largest_stderr_bytes=largest_stderr_bytes,
            largest_validation_output_bytes=largest_validation_output_bytes,
            service_tier_timeouts=service_tier_timeouts,
            service_tier_fallbacks=service_tier_fallbacks,
        )

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

    def pricing_for_role(
        self,
        model_role: str,
        inference_tier: str | None = None,
    ) -> ModelPricing:
        assert self.pricing is not None
        pricing = None
        if inference_tier:
            pricing = self.pricing.roles.get(f"{model_role}:{inference_tier}")
        if pricing is None:
            pricing = self.pricing.roles.get(model_role)
        if pricing is None and inference_tier is None:
            pricing = self.pricing.roles.get(f"{model_role}:default")
        if pricing is None:
            suffix = f":{inference_tier}" if inference_tier else ""
            raise BudgetExceeded(f"No pricing configured for model role: {model_role}{suffix}")
        return pricing

    def _role_budget(self, model_role: str) -> float:
        configured_role_budget = self.settings.role_budgets_usd.get(model_role)
        if configured_role_budget is not None:
            return configured_role_budget
        return self.settings.project_total_budget_usd
