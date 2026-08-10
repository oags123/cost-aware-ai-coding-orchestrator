from __future__ import annotations

import re
from pathlib import Path

from coding_orchestrator.config import HandoffSettings
from coding_orchestrator.orchestrator.handoff import HandoffBuilder, list_handoffs
from coding_orchestrator.schemas import (
    AttemptMetrics,
    ConvergenceDecision,
    OrchestratorState,
    TaskSpec,
)


def _task(**overrides: object) -> TaskSpec:
    defaults: dict[str, object] = {
        "id": "T-HANDOFF",
        "title": "Fix the thing",
        "description": "The thing is broken.",
        "allowed_files": ["pkg/thing.py"],
        "max_cost_usd": 0.05,
        "validation_commands": ["pytest -q"],
    }
    defaults.update(overrides)
    return TaskSpec.model_validate(defaults)


def _state(**overrides: object) -> OrchestratorState:
    defaults: dict[str, object] = {
        "request_id": "11111111-2222-3333-4444-555555555555",
        "user_request": "fix it",
        "task_id": "T-HANDOFF",
        "final_status": "escalated",
        "retry_count": 2,
        "estimated_cost_usd": 0.0031,
    }
    defaults.update(overrides)
    return OrchestratorState.model_validate(defaults)


def test_build_writes_a_single_self_contained_markdown_file(tmp_path: Path) -> None:
    builder = HandoffBuilder(HandoffSettings(), tmp_path / "handoffs")
    task = _task()
    state = _state()
    state.attempt_metrics = [
        AttemptMetrics(attempt_number=1, validation_status="failed", validator_error_count=2),
        AttemptMetrics(
            attempt_number=2,
            validation_status="failed",
            validator_error_count=2,
            repeated_failures=True,
        ),
    ]
    state.convergence_decision = ConvergenceDecision(
        status="stagnating",
        action="request_diagnosis",
        reason="same failures repeated",
        stagnant_attempts=2,
    )

    path = builder.build(
        task=task,
        state=state,
        reason="non_converging",
        diff="diff --git a/pkg/thing.py b/pkg/thing.py\n-broken\n+fixed\n",
        validation_errors=["tests: 2 failing"],
        budget_snapshot={"project total spend so far": "$0.0031"},
    )

    assert path.exists()
    assert path.parent == tmp_path / "handoffs"
    content = path.read_text(encoding="utf-8")

    # Frontmatter is present and parseable metadata a CLI/index can rely on.
    assert content.startswith("---\n")
    assert "task_id: T-HANDOFF" in content
    assert "reason: non_converging" in content

    # Human/ChatGPT-facing content: why it stopped, the task itself, evidence,
    # and instructions for what a useful response looks like.
    assert "Fix the thing" in content
    assert "stagnating" in content
    assert "tests: 2 failing" in content
    assert "diff --git a/pkg/thing.py" in content
    assert "$0.0031" in content
    assert "Task file schema" in content
    assert "allowed_files:" in content


def test_build_bounds_oversized_diff_and_validation_output(tmp_path: Path) -> None:
    settings = HandoffSettings(max_diff_chars=50, max_validation_chars=40)
    builder = HandoffBuilder(settings, tmp_path / "handoffs")
    task = _task()
    state = _state()

    path = builder.build(
        task=task,
        state=state,
        reason="budget_exceeded",
        diff="X" * 500,
        validation_errors=["Y" * 500],
    )

    content = path.read_text(encoding="utf-8")
    assert "truncated" in content
    # The bounded tail of the oversized diff/validation text is present, not the
    # full 500-character blob.
    assert "X" * 500 not in content
    assert "Y" * 500 not in content


def test_build_handles_no_attempts_and_no_validation_errors(tmp_path: Path) -> None:
    builder = HandoffBuilder(HandoffSettings(), tmp_path / "handoffs")
    task = _task()
    state = _state(retry_count=0)

    path = builder.build(task=task, state=state, reason="flex_unavailable")

    content = path.read_text(encoding="utf-8")
    assert "No attempts completed" in content
    assert "(none recorded)" in content


def test_list_handoffs_on_missing_directory_returns_empty(tmp_path: Path) -> None:
    assert list_handoffs(tmp_path / "does-not-exist") == []


def test_list_handoffs_enumerates_newest_first(tmp_path: Path) -> None:
    output_dir = tmp_path / "handoffs"
    builder = HandoffBuilder(HandoffSettings(), output_dir)

    older = builder.build(
        task=_task(id="T-OLD"),
        state=_state(task_id="T-OLD", request_id="00000000-0000-0000-0000-000000000001"),
        reason="non_converging",
    )
    # Force a distinct, later created_at so ordering is deterministic regardless
    # of how fast the two build() calls run.
    newer = builder.build(
        task=_task(id="T-NEW"),
        state=_state(task_id="T-NEW", request_id="00000000-0000-0000-0000-000000000002"),
        reason="retries_exhausted",
    )
    # Force a deterministically older created_at (independent of wall-clock
    # timing/date) so ordering doesn't depend on how fast the two build() calls run.
    older_text = re.sub(
        r"created_at: '.*'",
        "created_at: '2020-01-01T00:00:00+00:00'",
        older.read_text(encoding="utf-8"),
    )
    older.write_text(older_text, encoding="utf-8")

    records = list_handoffs(output_dir)

    assert len(records) == 2
    assert records[0]["task_id"] == "T-NEW"
    assert records[0]["reason"] == "retries_exhausted"
    assert records[1]["task_id"] == "T-OLD"
    assert str(newer) == records[0]["path"]
