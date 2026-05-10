from __future__ import annotations

import re
from dataclasses import dataclass

from coding_orchestrator.config import DiagnosisSettings
from coding_orchestrator.schemas import DiagnosisResult, OrchestratorState, ReviewPacket, TaskSpec


class DiagnosisError(RuntimeError):
    pass


FORBIDDEN_DIAGNOSIS_PATTERNS = (
    re.compile(r"^diff --git ", re.MULTILINE),
    re.compile(r"^--- .*\n\+\+\+ ", re.MULTILINE),
    re.compile(r"\b(write|overwrite|delete|create)\s+file\b", re.IGNORECASE),
    re.compile(
        r"\b(run|execute)\s+(pytest|ruff|mypy|git|python|sh|bash|curl|sudo)\b",
        re.IGNORECASE,
    ),
    re.compile(r"```(?:python|diff|bash|sh)?\n.{500,}?```", re.DOTALL | re.IGNORECASE),
)


@dataclass
class ReviewPacketBuilder:
    settings: DiagnosisSettings

    def build(
        self,
        *,
        task: TaskSpec,
        state: OrchestratorState,
        diff: str,
        logs: list[str],
        validation_errors: list[str],
        remaining_task_usd: float,
        projected_review_usd: float,
    ) -> ReviewPacket:
        packet = ReviewPacket(
            task={
                "id": task.id,
                "title": task.title,
                "complexity": task.complexity,
                "risk": task.risk,
                "allowed_files": task.allowed_files,
            },
            budget={
                "remaining_task_usd": remaining_task_usd,
                "projected_review_usd": projected_review_usd,
            },
            attempts={
                "count": len(state.attempt_metrics),
                "metrics": [item.model_dump() for item in state.attempt_metrics],
                "convergence": state.convergence_decision.model_dump()
                if state.convergence_decision
                else {},
            },
            diff={
                "changed_files": _changed_files_from_state(state),
                "compact_patch": _tail(diff, self.settings.max_diff_chars),
            },
            validation={
                "current_failures": validation_errors,
                "compact_stdout": _tail(
                    "\n".join(_stream(logs, "stdout")),
                    self.settings.max_stdout_chars,
                ),
                "compact_stderr": _tail(
                    "\n".join(_stream(logs, "stderr")),
                    self.settings.max_stderr_chars,
                ),
            },
            question={
                "type": "diagnosis",
                "prompt": (
                    "What is the most likely root cause and next cheap-builder instruction? "
                    "Return structured diagnosis only. Do not produce a patch, shell command, "
                    "file write, or code block."
                ),
            },
        )
        return _fit_packet(packet, self.settings.max_packet_chars)


@dataclass
class DiagnosisReviewer:
    settings: DiagnosisSettings

    def diagnose(self, packet: ReviewPacket) -> DiagnosisResult:
        if not self.settings.enabled:
            raise DiagnosisError("diagnosis reviewer is disabled")
        if not self.settings.diagnosis_only:
            raise DiagnosisError("expensive reviewer must remain diagnosis_only")
        if self.settings.allow_direct_patch:
            raise DiagnosisError("direct expensive-reviewer patches are disabled")
        if not self.settings.dry_run:
            raise DiagnosisError("real diagnosis reviewer integration is not implemented")
        result = DiagnosisResult(
            root_cause="Dry-run diagnosis placeholder: inspect validator failures and latest diff.",
            minimal_fix_strategy=(
                "Focus the next cheap-builder attempt on the current failing validators."
            ),
            files_to_focus=list(packet.task.get("allowed_files", [])),
            risks=["Dry-run diagnosis only; no provider reviewed this packet."],
            gemini_instruction=(
                "Use the validation failures and allowed files only. Produce the smallest patch "
                "that addresses the current failing validator output."
            ),
            confidence=0.4,
            should_retry_with_cheap_builder=True,
            risk_assessment="No real reviewer call was made; treat this as a routing artifact.",
            recommended_next_instruction=(
                "Use the validation failures and allowed files only. Produce the smallest patch "
                "that addresses the current failing validator output."
            ),
        )
        return validate_diagnosis_result(result, self.settings)


def validate_diagnosis_result(
    result: DiagnosisResult,
    settings: DiagnosisSettings,
) -> DiagnosisResult:
    if result.direct_patch_proposed or settings.allow_direct_patch:
        raise DiagnosisError("direct expensive-reviewer patches are disabled")
    text = result.model_dump_json()
    for pattern in FORBIDDEN_DIAGNOSIS_PATTERNS:
        if pattern.search(text):
            raise DiagnosisError("diagnosis reviewer output violates diagnosis-only contract")
    return result


def packet_to_prompt(packet: ReviewPacket) -> str:
    return packet.model_dump_json(indent=2)


def _fit_packet(packet: ReviewPacket, max_chars: int) -> ReviewPacket:
    for section, key in (
        ("diff", "compact_patch"),
        ("validation", "compact_stdout"),
        ("validation", "compact_stderr"),
    ):
        text = packet_to_prompt(packet)
        if len(text) <= max_chars:
            return packet
        overage = len(text) - max_chars
        container = getattr(packet, section)
        value = str(container.get(key, ""))
        container[key] = _tail(value, max(0, len(value) - overage))
    return packet


def _tail(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _stream(logs: list[str], marker: str) -> list[str]:
    return [log for log in logs if marker in log.lower()]


def _changed_files_from_state(state: OrchestratorState) -> list[str]:
    patch = state.tool_results.get("patch")
    if isinstance(patch, dict):
        touched = patch.get("touched_files", [])
        if isinstance(touched, list):
            return [str(item) for item in touched]
    return []
