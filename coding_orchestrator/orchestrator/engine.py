from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from coding_orchestrator.config import AppConfig
from coding_orchestrator.models.router import ModelRouter
from coding_orchestrator.observability.logger import JsonlLogger
from coding_orchestrator.orchestrator.budget import (
    BudgetEstimate,
    BudgetExceeded,
    BudgetGuard,
    BudgetUsage,
)
from coding_orchestrator.orchestrator.escalation import EscalationManager
from coding_orchestrator.orchestrator.limits import LimitExceeded, LimitGuard
from coding_orchestrator.orchestrator.router import TaskClassifier
from coding_orchestrator.orchestrator.state import StateStore
from coding_orchestrator.orchestrator.tier_policy import CheapBuilderTierPolicy
from coding_orchestrator.orchestrator.timeouts import TimeoutExceeded, TimeoutGuard
from coding_orchestrator.orchestrator.workflows import WORKFLOWS
from coding_orchestrator.schemas import (
    BuilderResult,
    OrchestratorState,
    TaskSpec,
    ValidationResult,
    load_task_file,
)
from coding_orchestrator.tools.git import GitCheckpoint, GitManager
from coding_orchestrator.tools.opencode_runner import OpenCodeExecutionError, OpenCodeRunner
from coding_orchestrator.tools.patch import SafePatchApplier, parse_builder_output
from coding_orchestrator.validators.code_validator import SyntaxValidator
from coding_orchestrator.validators.patch_validator import PatchValidator
from coding_orchestrator.validators.safety_validator import CommandSafetyValidator
from coding_orchestrator.validators.test_validator import TestValidator


class DependencyError(RuntimeError):
    pass


class CommitFailed(RuntimeError):
    pass


class WorkflowEngine:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.repo_path = Path(config.repo_path).resolve()
        self.classifier = TaskClassifier()
        self.model_router = ModelRouter(config.model_routing)
        budget_settings = config.budget
        ledger_path = Path(budget_settings.ledger_path)
        if not ledger_path.is_absolute():
            budget_settings = budget_settings.model_copy(
                update={"ledger_path": str((self.repo_path / ledger_path).resolve())}
            )
        self.budget = BudgetGuard(budget_settings, config.pricing)
        self.limits = LimitGuard(config.limits)
        self.tier_policy = CheapBuilderTierPolicy(config.inference.cheap_builder)
        self.logger = JsonlLogger(Path(config.log_path))
        self.state_store = StateStore(Path(config.state_path))
        self.escalation = EscalationManager(Path("logs/escalations"))
        self.git = GitManager(self.repo_path)
        self.patch_applier = SafePatchApplier(
            self.repo_path,
            self.config.validation,
            self.config.timeouts.max_attempt_runtime_seconds,
        )

    def run_task_file(self, task_path: Path) -> OrchestratorState:
        return self.run_task(load_task_file(task_path))

    def run_task(self, task: TaskSpec) -> OrchestratorState:
        state = self._initial_state(task)
        max_runtime = min(task.max_runtime_seconds, self.config.timeouts.max_task_runtime_seconds)
        guard = TimeoutGuard(max_runtime)
        self.logger.log("task_started", request_id=state.request_id, task_id=task.id)
        validation_errors: list[str] = []
        checkpoint: GitCheckpoint | None = None
        try:
            checkpoint = self.git.checkpoint(task.id, self.config.git.require_clean_worktree)
            if state.requires_human_approval:
                state.final_status = "blocked"
                return self._finish(state, "task_blocked")
            while state.retry_count < task.max_attempts:
                guard.check()
                state.final_status = "running"
                self._run_builder_step(task, state, validation_errors)
                results = self.limits.enforce_validation_output(self._validate(task))
                state.validation_results = {result.name: result.model_dump() for result in results}
                validation_errors = [result.message for result in results if not result.passed]
                if any(
                    "validation_output_limit_exceeded" in error
                    for error in validation_errors
                ):
                    self._record_limit_failure(state, "validation_output_limit_exceeded")
                if not validation_errors:
                    self._commit(task, state)
                    state.final_status = "completed"
                    self.budget.record(state)
                    return self._finish(state, "task_completed")
                self.logger.log(
                    "validation_failed",
                    request_id=state.request_id,
                    task_id=task.id,
                    errors=validation_errors,
                    retry=state.retry_count,
                )
                state.retry_count += 1
            self._handle_failure(task, state, validation_errors, checkpoint)
            return state
        except TimeoutExceeded as exc:
            state.final_status = "timeout"
            validation_errors.append(str(exc))
            self._rollback_if_checkpoint(checkpoint)
            self._escalate_if_allowed(task, state, validation_errors)
            return self._finish(state, "task_timeout")
        except BudgetExceeded as exc:
            state.final_status = "blocked"
            validation_errors.append(str(exc))
            self._rollback_if_checkpoint(checkpoint)
            state.validation_results["budget"] = {
                "name": "budget",
                "passed": False,
                "message": str(exc),
                "details": state.tool_results.get("budget_estimate", {}),
            }
            return self._finish(state, "task_budget_blocked")
        except LimitExceeded as exc:
            state.final_status = "blocked"
            validation_errors.append(exc.message)
            self._rollback_if_checkpoint(checkpoint)
            state.validation_results["limits"] = {
                "name": "limits",
                "passed": False,
                "message": exc.message,
                "details": {"status": exc.status},
            }
            self._record_limit_failure(state, exc.status)
            return self._finish(state, exc.status)
        except Exception as exc:
            state.final_status = "failed"
            validation_errors.append(str(exc))
            self._rollback_if_checkpoint(checkpoint)
            self._escalate_if_allowed(task, state, validation_errors)
            return self._finish(state, "task_failed")

    def run_all(self, tasks_dir: Path) -> list[OrchestratorState]:
        tasks = [load_task_file(path) for path in sorted(tasks_dir.glob("*")) if path.is_file()]
        ordered = order_tasks(tasks)
        completed: set[str] = set()
        states: list[OrchestratorState] = []
        for task in ordered:
            if any(dep not in completed for dep in task.depends_on):
                state = self._initial_state(task)
                state.final_status = "skipped"
                states.append(self._finish(state, "task_skipped_blocked_dependency"))
                continue
            state = self.run_task(task)
            states.append(state)
            if state.final_status == "completed":
                completed.add(task.id)
        return states

    def budget_report(self) -> BudgetUsage:
        metrics = self.limits.metrics
        return self.budget.report(
            limit_failures=metrics.limit_failures,
            largest_patch_bytes=metrics.largest_patch_bytes,
            largest_stdout_bytes=metrics.largest_stdout_bytes,
            largest_stderr_bytes=metrics.largest_stderr_bytes,
            largest_validation_output_bytes=metrics.largest_validation_output_bytes,
            flex_timeouts=self.tier_policy.state.flex_timeouts,
            standard_fallbacks=self.tier_policy.state.standard_fallbacks,
        )

    def _initial_state(self, task: TaskSpec) -> OrchestratorState:
        complexity = self.classifier.classify_complexity(task)
        risk = self.classifier.classify_risk(task)
        workflow = self.classifier.select_workflow(task)
        model = self.model_router.select_model(complexity, risk)
        state = OrchestratorState(
            request_id=str(uuid4()),
            user_request=task.description or task.title,
            task_id=task.id,
            task_type=self.classifier.classify_task_type(task),
            complexity=complexity,
            risk_level=risk,
            repo_path=str(self.repo_path),
            relevant_files=task.allowed_files,
            selected_model=model,
            selected_workflow=workflow,
            requires_human_approval=model == "human-approval",
        )
        state.estimated_input_tokens = max(1, len(state.user_request) // 4)
        state.estimated_output_tokens = 1000
        state.estimated_cost_usd = self.budget.estimate(state.user_request)
        if not self.budget.can_spend(task, state):
            state.requires_human_approval = True
        return state

    def _run_builder_step(
        self,
        task: TaskSpec,
        state: OrchestratorState,
        validation_errors: list[str],
    ) -> None:
        workflow = WORKFLOWS[state.selected_workflow or "fix_bug"]
        context = workflow.build_context(task, state)
        if validation_errors:
            context += "\n\nPrevious validation feedback:\n" + self._compact_feedback(state)
        try:
            context = self.limits.prepare_context(context)
        except LimitExceeded:
            tier = self.tier_policy.select_tier()
            pricing = self.budget.pricing_for_role("cheap_builder", tier)
            estimate = self.budget.estimate_pre_call(
                task=task,
                attempt_id=state.retry_count + 1,
                model_role="cheap_builder",
                context=context,
                model_override=pricing.model,
                inference_tier=tier,
            )
            state.estimated_input_tokens = estimate.estimated_input_tokens
            state.estimated_output_tokens = estimate.estimated_output_tokens
            state.estimated_cost_usd = estimate.estimated_total_cost_usd
            state.tool_results["budget_estimate"] = estimate.model_dump()
            raise
        state.retrieved_context = [context]
        response = self._run_tiered_builder(task, state, context)
        response = self.limits.check_builder_output(response)
        state.tool_results["builder"] = {
            "model": state.tool_results.get("builder_model"),
            "tier": state.tool_results.get("builder_tier"),
            "confidence": response.confidence,
            "text": response.text,
            "returncode": response.returncode,
            "stderr": response.stderr[-4000:],
            "timed_out": response.timed_out,
            "dry_run": response.dry_run,
        }
        if response.dry_run:
            return
        parsed = parse_builder_output(response.text)
        if parsed is None:
            return
        self.limits.check_patch(parsed)
        self.patch_applier.apply(parsed, task)
        state.tool_results["patch"] = parsed.model_dump()

    def _run_tiered_builder(
        self,
        task: TaskSpec,
        state: OrchestratorState,
        context: str,
    ) -> BuilderResult:
        while True:
            tier = self.tier_policy.select_tier()
            pricing = self.budget.pricing_for_role("cheap_builder", tier)
            estimate = self.budget.estimate_pre_call(
                task=task,
                attempt_id=state.retry_count + 1,
                model_role="cheap_builder",
                context=context,
                model_override=pricing.model,
                inference_tier=tier,
            )
            if tier == "standard":
                try:
                    self.tier_policy.check_standard_fallback(estimate)
                except BudgetExceeded:
                    self.budget.record_estimate(estimate, status="blocked")
                    raise
            self._prepare_builder_call(task, state, estimate)
            self.tier_policy.record_call(tier)
            runner_settings = self.config.opencode.model_copy(
                update={
                    "default_model": pricing.model,
                    "max_runtime_seconds": self.tier_policy.timeout_seconds(
                        tier,
                        self.config.opencode.max_runtime_seconds,
                    ),
                }
            )
            runner = OpenCodeRunner(self.repo_path, pricing.model, runner_settings)
            try:
                response = runner.run_bounded_step(task, context)
            except OpenCodeExecutionError as exc:
                if tier == "flex" and exc.timed_out:
                    self.tier_policy.record_flex_timeout()
                    state.tool_results["builder_timeout"] = {
                        "tier": tier,
                        "message": str(exc),
                    }
                    if self.tier_policy.should_fallback_to_standard():
                        self.tier_policy.activate_fallback()
                        continue
                raise
            self.tier_policy.record_success(tier)
            state.tool_results["builder_tier"] = tier
            state.tool_results["builder_model"] = pricing.model
            return response

    def _prepare_builder_call(
        self,
        task: TaskSpec,
        state: OrchestratorState,
        estimate: BudgetEstimate,
    ) -> None:
        state.estimated_input_tokens = estimate.estimated_input_tokens
        state.estimated_output_tokens = estimate.estimated_output_tokens
        state.estimated_cost_usd = estimate.estimated_total_cost_usd
        state.tool_results["budget_estimate"] = estimate.model_dump()
        self.limits.check_pre_call(estimate)
        self.budget.check_pre_call(task, estimate)
        self.budget.record_estimate(estimate, status="estimated")

    def _validate(self, task: TaskSpec) -> list[ValidationResult]:
        changed = self.git.changed_files()
        commands = task.validation_commands or self.config.validation.default_commands
        timeout = self.config.timeouts.max_attempt_runtime_seconds
        return [
            CommandSafetyValidator(
                commands,
                self.config.tool_permissions.allowlisted_shell_commands,
            ).validate(),
            PatchValidator(
                changed,
                self.repo_path,
                task.allowed_files,
                self.config.validation,
            ).validate(),
            SyntaxValidator(self.repo_path, timeout).validate(),
            TestValidator(commands, self.repo_path, timeout).validate(),
        ]

    def _commit(self, task: TaskSpec, state: OrchestratorState) -> None:
        result = self.git.commit_task(task.id, task.title, task.allowed_files)
        state.tool_results["git_commit"] = result.model_dump()
        if result.returncode != 0:
            raise CommitFailed(result.stderr or result.stdout or "git commit failed")

    def _handle_failure(
        self,
        task: TaskSpec,
        state: OrchestratorState,
        validation_errors: list[str],
        checkpoint: GitCheckpoint,
    ) -> None:
        self.git.rollback_to_checkpoint(
            checkpoint,
            self.config.git.preserve_untracked_dirs,
            self.config.git.preserve_untracked_files,
        )
        if self._escalate_if_allowed(task, state, validation_errors):
            state.final_status = "escalated"
        else:
            state.final_status = "failed"
        self._finish(state, state.final_status)

    def _escalate_if_allowed(
        self,
        task: TaskSpec,
        state: OrchestratorState,
        validation_errors: list[str],
    ) -> bool:
        if not self.escalation.should_escalate(task, state, validation_errors):
            return False
        path = self.escalation.create_package(
            task=task,
            state=state,
            diff=self.git.diff(),
            logs=self._collect_relevant_logs(state),
            validation_errors=validation_errors,
        )
        state.tool_results["escalation_package"] = str(path)
        self.logger.log(
            "task_escalated",
            request_id=state.request_id,
            task_id=task.id,
            path=str(path),
        )
        return True

    def _finish(self, state: OrchestratorState, event: str) -> OrchestratorState:
        state.finished_at = datetime.now(UTC)
        self.state_store.append(state)
        self.logger.log(
            event,
            request_id=state.request_id,
            task_id=state.task_id,
            status=state.final_status,
            retries=state.retry_count,
            cost=state.estimated_cost_usd,
        )
        return state

    def _rollback_if_checkpoint(self, checkpoint: GitCheckpoint | None) -> None:
        if checkpoint is None:
            return
        self.git.rollback_to_checkpoint(
            checkpoint,
            self.config.git.preserve_untracked_dirs,
            self.config.git.preserve_untracked_files,
        )

    def _compact_feedback(self, state: OrchestratorState) -> str:
        lines: list[str] = []
        for name, result in state.validation_results.items():
            if not isinstance(result, dict) or result.get("passed"):
                continue
            lines.append(f"{name}: {result.get('message', '')}")
            details = result.get("details", {})
            if isinstance(details, dict):
                for command, command_result in details.items():
                    if isinstance(command_result, dict):
                        stdout = str(command_result.get("stdout", ""))[-1000:]
                        stderr = str(command_result.get("stderr", ""))[-1000:]
                        if stdout:
                            lines.append(f"{command} stdout:\n{stdout}")
                        if stderr:
                            lines.append(f"{command} stderr:\n{stderr}")
        feedback = "\n".join(lines[-20:])
        return feedback[-self.config.limits.max_retry_context_chars :]

    def _collect_relevant_logs(self, state: OrchestratorState) -> list[str]:
        logs: list[str] = []
        for key in ("builder", "git_commit"):
            value = state.tool_results.get(key)
            if isinstance(value, dict):
                stderr = str(value.get("stderr", ""))[-4000:]
                stdout = str(value.get("stdout", ""))[-4000:]
                if stdout:
                    logs.append(f"{key} stdout:\n{stdout}")
                if stderr:
                    logs.append(f"{key} stderr:\n{stderr}")
        return logs

    def _record_limit_failure(self, state: OrchestratorState, status: str) -> None:
        estimate_data = state.tool_results.get("budget_estimate")
        if not isinstance(estimate_data, dict):
            return
        try:
            estimate = self.budget_estimate_from_dict(estimate_data)
        except ValueError:
            return
        self.budget.record_estimate(estimate, status=status)

    def budget_estimate_from_dict(self, data: dict[str, object]) -> BudgetEstimate:
        return BudgetEstimate.model_validate(data)


def order_tasks(tasks: list[TaskSpec]) -> list[TaskSpec]:
    by_id = {task.id: task for task in tasks}
    ordered: list[TaskSpec] = []
    temporary: set[str] = set()
    permanent: set[str] = set()

    def visit(task: TaskSpec) -> None:
        if task.id in permanent:
            return
        if task.id in temporary:
            raise DependencyError(f"Cycle detected at {task.id}")
        temporary.add(task.id)
        for dep in task.depends_on:
            if dep in by_id:
                visit(by_id[dep])
        temporary.remove(task.id)
        permanent.add(task.id)
        ordered.append(task)

    for item in tasks:
        visit(item)
    return ordered
