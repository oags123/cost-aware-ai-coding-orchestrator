from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from coding_orchestrator.config import ConvergenceSettings
from coding_orchestrator.schemas import (
    AttemptMetrics,
    ConvergenceDecision,
    ConvergenceDecisionAction,
    ConvergenceStatus,
    ValidationResult,
)


@dataclass
class ConvergenceEvaluator:
    settings: ConvergenceSettings
    stagnant_attempts: int = 0
    divergent_attempts: int = 0
    decisions: list[ConvergenceDecision] = field(default_factory=list)

    def collect_attempt_metrics(
        self,
        *,
        attempt_number: int,
        validation_results: list[ValidationResult],
        changed_files: list[str],
        allowed_files: list[str],
        tool_results: dict[str, Any],
        previous: AttemptMetrics | None = None,
    ) -> AttemptMetrics:
        failing_results = [result for result in validation_results if not result.passed]
        signatures = _failure_signatures(failing_results)
        previous_signatures = set(previous.failure_signatures if previous else [])
        signature_set = set(signatures)
        return AttemptMetrics(
            attempt_number=attempt_number,
            validation_status="failed" if failing_results else "passed",
            failing_test_count=_failing_test_count(validation_results),
            validator_error_count=len(failing_results),
            changed_file_count=len(changed_files),
            patch_size_bytes=_patch_size(tool_results),
            stdout_size_bytes=_builder_stream_size(tool_results, "stdout"),
            stderr_size_bytes=_builder_stream_size(tool_results, "stderr"),
            failure_categories=_failure_categories(failing_results),
            failure_signatures=signatures,
            repeated_failures=bool(signature_set & previous_signatures),
            new_failures=(
                bool(signature_set - previous_signatures) if previous else bool(signatures)
            ),
            unrelated_file_touch=bool(allowed_files)
            and any(path not in allowed_files for path in changed_files),
            syntax_regression=_has_syntax_failure(failing_results)
            and not (previous and previous.syntax_regression),
        )

    def evaluate(
        self,
        current: AttemptMetrics,
        previous: AttemptMetrics | None = None,
    ) -> ConvergenceDecision:
        if current.validation_status == "passed":
            decision = ConvergenceDecision(
                status="converging",
                action="continue_current_role_retry",
                improvement_score=10.0,
                reason="validation passed",
                stagnant_attempts=self.stagnant_attempts,
                divergent_attempts=self.divergent_attempts,
            )
            self.decisions.append(decision)
            return decision

        score = 0.0
        reasons: list[str] = []
        if previous is not None:
            score += _trend_score(
                previous.validator_error_count,
                current.validator_error_count,
                2.0,
            )
            score += _trend_score(previous.failing_test_count, current.failing_test_count, 1.5)
            score += _trend_score(previous.changed_file_count, current.changed_file_count, 1.0)
            score += _trend_score(previous.patch_size_bytes, current.patch_size_bytes, 1.0)
            if current.validator_error_count < previous.validator_error_count:
                reasons.append("validator errors decreased")
            if current.failing_test_count < previous.failing_test_count:
                reasons.append("failing tests decreased")
            if current.changed_file_count < previous.changed_file_count:
                reasons.append("patch scope shrank")
            if current.patch_size_bytes < previous.patch_size_bytes:
                reasons.append("patch size shrank")

        divergent = self._is_divergent(current, previous, score)
        stagnant = self._is_stagnant(current, previous, score)

        if divergent:
            self.divergent_attempts += 1
            self.stagnant_attempts = 0
            status: ConvergenceStatus = "diverging"
            action: ConvergenceDecisionAction = "request_diagnosis"
            reasons.append("divergence threshold met")
        elif stagnant:
            self.stagnant_attempts += 1
            status = "stagnating"
            action = "continue_current_role_retry"
            reasons.append("same failures repeated")
        else:
            self.stagnant_attempts = 0
            self.divergent_attempts = 0
            status = "converging"
            action = "continue_current_role_retry"
            if not reasons:
                reasons.append("retry remains within convergence thresholds")

        if self.stagnant_attempts > self.settings.max_stagnant_attempts:
            status = "non_converging"
            action = "request_diagnosis"
            reasons.append("stagnation limit exceeded")
        if self.divergent_attempts > self.settings.max_divergent_attempts:
            status = "non_converging"
            action = "request_diagnosis"
            reasons.append("divergence limit exceeded")
        if action == "request_diagnosis" and (
            current.unrelated_file_touch or current.syntax_regression
        ):
            action = "pause_block_task"

        decision = ConvergenceDecision(
            status=status,
            action=action,
            improvement_score=score,
            reason="; ".join(reasons),
            stagnant_attempts=self.stagnant_attempts,
            divergent_attempts=self.divergent_attempts,
        )
        self.decisions.append(decision)
        return decision

    def report(self) -> dict[str, Any]:
        latest = self.decisions[-1] if self.decisions else ConvergenceDecision()
        return {
            "status": latest.status,
            "action": latest.action,
            "improvement_score": latest.improvement_score,
            "reason": latest.reason,
            "stagnant_attempts": self.stagnant_attempts,
            "divergent_attempts": self.divergent_attempts,
        }

    def _is_stagnant(
        self,
        current: AttemptMetrics,
        previous: AttemptMetrics | None,
        score: float,
    ) -> bool:
        if previous is None:
            return False
        return current.repeated_failures and not current.new_failures and score <= 0

    def _is_divergent(
        self,
        current: AttemptMetrics,
        previous: AttemptMetrics | None,
        score: float,
    ) -> bool:
        if self.settings.hard_stop_on_unrelated_file_touch and current.unrelated_file_touch:
            return True
        if self.settings.hard_stop_on_syntax_regression and current.syntax_regression:
            return True
        if current.new_failures and previous is not None:
            return True
        if score < self.settings.min_improvement_score_to_continue:
            return True
        if previous is None:
            return False
        return (
            _growth_ratio(previous.patch_size_bytes, current.patch_size_bytes)
            > self.settings.max_patch_growth_ratio
            or _growth_ratio(previous.validator_error_count, current.validator_error_count)
            > self.settings.max_failure_growth_ratio
        )


def _failure_signatures(results: list[ValidationResult]) -> list[str]:
    return sorted(f"{result.name}:{result.message}" for result in results)


def _failure_categories(results: list[ValidationResult]) -> list[str]:
    categories: set[str] = set()
    for result in results:
        name = result.name.lower()
        message = result.message.lower()
        if name == "syntax":
            categories.add("syntax")
        if "mypy" in message or _details_include(result.details, "mypy"):
            categories.add("mypy")
        if "ruff" in message or _details_include(result.details, "ruff"):
            categories.add("ruff")
        if "pytest" in message or "tests" in name or _details_include(result.details, "pytest"):
            categories.add("pytest")
        if name == "patch":
            categories.add("patch")
    return sorted(categories)


def _details_include(details: dict[str, Any], text: str) -> bool:
    return text in str(details).lower()


def _failing_test_count(results: list[ValidationResult]) -> int:
    for result in results:
        if result.name != "tests":
            continue
        count = 0
        for value in result.details.values():
            if isinstance(value, dict) and value.get("returncode", 0) != 0:
                count += 1
        return count
    return 0


def _has_syntax_failure(results: list[ValidationResult]) -> bool:
    return any(result.name == "syntax" and not result.passed for result in results)


def _patch_size(tool_results: dict[str, Any]) -> int:
    patch = tool_results.get("patch")
    if isinstance(patch, dict):
        return len(str(patch.get("patch", "")).encode("utf-8"))
    builder = tool_results.get("builder")
    if isinstance(builder, dict):
        return len(str(builder.get("text", "")).encode("utf-8"))
    return 0


def _builder_stream_size(tool_results: dict[str, Any], key: str) -> int:
    builder = tool_results.get("builder")
    if not isinstance(builder, dict):
        return 0
    return len(str(builder.get(key, "")).encode("utf-8"))


def _trend_score(previous: int, current: int, weight: float) -> float:
    if current < previous:
        return weight
    if current > previous:
        return -weight
    return 0.0


def _growth_ratio(previous: int, current: int) -> float:
    baseline = max(previous, 1)
    return current / baseline
