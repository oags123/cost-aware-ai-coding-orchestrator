from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from coding_orchestrator.config import AppConfig
from coding_orchestrator.models.router import ModelRouter
from coding_orchestrator.observability.logger import JsonlLogger
from coding_orchestrator.observability.telegram import TelegramAlert, TelegramNotifier
from coding_orchestrator.orchestrator.budget import (
    BudgetEstimate,
    BudgetExceeded,
    BudgetGuard,
    BudgetUsage,
)
from coding_orchestrator.orchestrator.convergence import ConvergenceEvaluator
from coding_orchestrator.orchestrator.diagnosis import (
    DiagnosisError,
    DiagnosisReviewer,
    ReviewPacketBuilder,
    packet_to_prompt,
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
    ConvergenceDecision,
    OrchestratorState,
    ReviewPacket,
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
        self.convergence = ConvergenceEvaluator(config.convergence)
        self.review_packet_builder = ReviewPacketBuilder(config.diagnosis)
        self.diagnosis_reviewer = DiagnosisReviewer(config.diagnosis)
        self.reviewer_calls_this_run = 0
        self.reviewer_calls_by_task: dict[str, int] = {}
        self.logger = JsonlLogger(Path(config.log_path))
        self.telegram = TelegramNotifier(config.telegram, budget_settings)
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
                    self._record_attempt_metrics(task, state, results)
                    self._commit(task, state)
                    state.final_status = "completed"
                    self.budget.record(state)
                    return self._finish(state, "task_completed")
                decision = self._record_attempt_metrics(task, state, results)
                self.logger.log(
                    "validation_failed",
                    request_id=state.request_id,
                    task_id=task.id,
                    errors=validation_errors,
                    retry=state.retry_count,
                    convergence=decision.model_dump(),
                )
                if decision.action in {
                    "request_diagnosis",
                    "pause_block_task",
                    "mark_non_converging",
                }:
                    if self._handle_non_converging(task, state, validation_errors, checkpoint):
                        state.retry_count += 1
                        continue
                    return state
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
        if not completed and self.config.telegram.notify_on_no_runnable_tasks:
            self._send_telegram_alert(
                TelegramAlert(
                    project_id=self.budget.settings.project_id,
                    reason="no_runnable_tasks",
                    completed_count=0,
                    blocked_count=sum(1 for state in states if state.final_status != "completed"),
                    estimated_cost_spent=self.budget_report().project_total_spend_usd,
                    budget_remaining=self.budget_report().project_total_remaining_usd,
                    recommended_next_action="Review blocked task dependencies and task states.",
                )
            )
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

    def convergence_report(self) -> dict[str, object]:
        return self.convergence.report()

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
        guidance = self._diagnosis_guidance(state)
        if guidance:
            context += "\n\nDiagnosis-only reviewer guidance for cheap retry:\n" + guidance
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

    def _record_attempt_metrics(
        self,
        task: TaskSpec,
        state: OrchestratorState,
        results: list[ValidationResult],
    ) -> ConvergenceDecision:
        previous = state.attempt_metrics[-1] if state.attempt_metrics else None
        metrics = self.convergence.collect_attempt_metrics(
            attempt_number=state.retry_count + 1,
            validation_results=results,
            changed_files=self.git.changed_files(),
            allowed_files=task.allowed_files,
            tool_results=state.tool_results,
            previous=previous,
        )
        decision = self.convergence.evaluate(metrics, previous)
        state.attempt_metrics.append(metrics)
        state.convergence_status = decision.status
        state.convergence_decision = decision
        state.tool_results["convergence"] = decision.model_dump()
        self.logger.log(
            "attempt_metrics",
            request_id=state.request_id,
            task_id=task.id,
            metrics=metrics.model_dump(),
            convergence=decision.model_dump(),
        )
        return decision

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

    def _handle_non_converging(
        self,
        task: TaskSpec,
        state: OrchestratorState,
        validation_errors: list[str],
        checkpoint: GitCheckpoint,
    ) -> bool:
        self.git.rollback_to_checkpoint(
            checkpoint,
            self.config.git.preserve_untracked_dirs,
            self.config.git.preserve_untracked_files,
        )
        if (
            state.convergence_decision
            and state.convergence_decision.action == "request_diagnosis"
            and self.config.diagnosis.enabled
        ):
            review_packet = self._build_review_packet(task, state, validation_errors)
            state.tool_results["review_packet"] = review_packet.model_dump()
            try:
                self._run_diagnosis_reviewer(task, state, review_packet)
            except (BudgetExceeded, LimitExceeded, DiagnosisError) as exc:
                state.tool_results["diagnosis_error"] = str(exc)
                if isinstance(exc, BudgetExceeded):
                    state.validation_results["budget"] = {
                        "name": "budget",
                        "passed": False,
                        "message": str(exc),
                        "details": state.tool_results.get("diagnosis_budget_estimate", {}),
                    }
                    state.final_status = "blocked"
                self._create_diagnosis_needed_package(task, state, validation_errors, review_packet)
                self._finish(state, "diagnosis_needed")
                return False
            diagnosis = state.tool_results.get("diagnosis", {})
            if (
                isinstance(diagnosis, dict)
                and diagnosis.get("should_retry_with_cheap_builder")
                and state.retry_count + 1 < task.max_attempts
            ):
                state.tool_results["reviewer_guidance"] = {
                    "gemini_instruction": diagnosis.get("gemini_instruction", ""),
                    "summary": diagnosis.get("minimal_fix_strategy", ""),
                    "files_to_focus": diagnosis.get("files_to_focus", []),
                }
                self.logger.log(
                    "diagnosis_guided_retry",
                    request_id=state.request_id,
                    task_id=task.id,
                    diagnosis=diagnosis,
                )
                return True
        if state.convergence_status == "diverging":
            state.final_status = "blocked"
        else:
            state.final_status = "escalated"
        self._create_diagnosis_needed_package(task, state, validation_errors)
        self._finish(state, "diagnosis_needed")
        return False

    def _build_review_packet(
        self,
        task: TaskSpec,
        state: OrchestratorState,
        validation_errors: list[str],
    ) -> ReviewPacket:
        return self.review_packet_builder.build(
            task=task,
            state=state,
            diff=self.git.diff(),
            logs=self._collect_relevant_logs(state),
            validation_errors=validation_errors,
            remaining_task_usd=max(0.0, task.max_cost_usd - state.estimated_cost_usd),
            projected_review_usd=0.0,
        )

    def _create_diagnosis_needed_package(
        self,
        task: TaskSpec,
        state: OrchestratorState,
        validation_errors: list[str],
        review_packet: ReviewPacket | None = None,
    ) -> None:
        diff = self.git.diff()
        logs = self._collect_relevant_logs(state)
        review_packet = review_packet or self._build_review_packet(task, state, validation_errors)
        state.tool_results["review_packet"] = review_packet.model_dump()
        path = self.escalation.create_package(
            task=task,
            state=state,
            diff=diff,
            logs=[
                "diagnosis_needed: cheap builder is non-converging; "
                "future diagnosis-only reviewer should inspect this package.",
                *logs,
            ],
            validation_errors=validation_errors,
        )
        state.tool_results["diagnosis_needed_package"] = str(path)
        self.logger.log(
            "diagnosis_needed",
            request_id=state.request_id,
            task_id=task.id,
            path=str(path),
            convergence=state.convergence_decision.model_dump()
            if state.convergence_decision
            else {},
        )

    def _run_diagnosis_reviewer(
        self,
        task: TaskSpec,
        state: OrchestratorState,
        review_packet: ReviewPacket,
    ) -> None:
        prompt = packet_to_prompt(review_packet)
        self._check_reviewer_call_limits(task.id)
        if len(prompt) > self.config.diagnosis.max_context_chars:
            raise LimitExceeded(
                "context_limit_exceeded",
                "diagnosis review packet exceeds max_context_chars",
            )
        estimate = self.budget.estimate_pre_call(
            task=task,
            attempt_id=len(state.attempt_metrics) + 1,
            model_role=self.config.diagnosis.model_role,
            context=prompt,
            model_override=self.config.diagnosis.model,
        )
        state.tool_results["diagnosis_budget_estimate"] = estimate.model_dump()
        if estimate.estimated_input_tokens > self.config.diagnosis.max_input_tokens:
            raise LimitExceeded(
                "context_limit_exceeded",
                "diagnosis input tokens exceed max_input_tokens",
            )
        if estimate.estimated_output_tokens > self.config.diagnosis.max_output_tokens:
            raise LimitExceeded(
                "output_limit_exceeded",
                "diagnosis output tokens exceed max_output_tokens",
            )
        if estimate.estimated_total_cost_usd > self.config.diagnosis.max_cost_per_call_usd:
            self.budget.record_estimate(estimate, status="blocked")
            raise BudgetExceeded("diagnosis reviewer max_cost_per_call_usd exceeded")
        self.limits.check_pre_call(estimate)
        self.budget.check_pre_call(task, estimate)
        self.budget.record_estimate(estimate, status="estimated")
        try:
            diagnosis = self.diagnosis_reviewer.diagnose(review_packet)
        except DiagnosisError as exc:
            state.tool_results["diagnosis_error"] = str(exc)
            raise
        state.tool_results["diagnosis"] = diagnosis.model_dump()
        self._record_reviewer_call(task.id)

    def _check_reviewer_call_limits(self, task_id: str) -> None:
        if self.reviewer_calls_this_run >= self.config.diagnosis.max_calls_per_run:
            raise BudgetExceeded("diagnosis reviewer max_calls_per_run exceeded")
        task_calls = self.reviewer_calls_by_task.get(task_id, 0)
        if task_calls >= self.config.diagnosis.max_calls_per_task:
            raise BudgetExceeded("diagnosis reviewer max_calls_per_task exceeded")

    def _record_reviewer_call(self, task_id: str) -> None:
        self.reviewer_calls_this_run += 1
        self.reviewer_calls_by_task[task_id] = self.reviewer_calls_by_task.get(task_id, 0) + 1

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
        if self.config.telegram.notify_on_blocked:
            self._notify_state(
                "human_attention_needed",
                state,
                "Review the escalation package and decide the next bounded action.",
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
        self._notify_on_finish(state, event)
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

    def _diagnosis_guidance(self, state: OrchestratorState) -> str:
        guidance = state.tool_results.get("reviewer_guidance")
        if not isinstance(guidance, dict):
            return ""
        parts = [
            str(guidance.get("gemini_instruction", "")),
            str(guidance.get("summary", "")),
        ]
        files = guidance.get("files_to_focus", [])
        if isinstance(files, list) and files:
            parts.append("Files to focus: " + ", ".join(str(item) for item in files))
        return "\n".join(part for part in parts if part)[
            -self.config.limits.max_retry_context_chars :
        ]

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

    def _notify_on_finish(self, state: OrchestratorState, event: str) -> None:
        if state.final_status == "blocked" and self.config.telegram.notify_on_blocked:
            reason = "blocked"
            if event == "task_budget_blocked" and self.config.telegram.notify_on_budget_exhausted:
                reason = "budget_exhausted"
            self._notify_state(reason, state, "Inspect task state and budget/validator details.")
        elif state.final_status == "timeout" and self.config.telegram.notify_on_runtime_exhausted:
            self._notify_state(
                "runtime_exhausted",
                state,
                "Review timeout settings or split the task into smaller work.",
            )
        elif state.final_status == "failed" and self.config.telegram.notify_on_system_error:
            self._notify_state(
                "system_error",
                state,
                "Inspect logs and escalation package before retrying.",
            )
        elif state.final_status == "escalated" and self.config.telegram.notify_on_blocked:
            self._notify_state(
                "human_attention_needed",
                state,
                "Review escalation package and decide whether to retry or intervene.",
            )

    def _notify_state(
        self,
        reason: str,
        state: OrchestratorState,
        recommended_next_action: str,
    ) -> None:
        usage = self.budget_report()
        alert = self.telegram.alert_from_state(
            reason=reason,
            state=state,
            usage=usage,
            recommended_next_action=recommended_next_action,
        )
        self._send_telegram_alert(alert)

    def _send_telegram_alert(self, alert: TelegramAlert) -> None:
        warning = self.telegram.send_alert(alert)
        if warning:
            self.logger.log(
                "telegram_warning",
                reason=alert.reason,
                warning=warning,
            )


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
