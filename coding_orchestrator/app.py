from __future__ import annotations

import argparse
import json
from pathlib import Path

from coding_orchestrator.config import load_config
from coding_orchestrator.orchestrator.engine import WorkflowEngine
from coding_orchestrator.orchestrator.handoff import list_handoffs
from coding_orchestrator.schemas import TaskSpec


def build_parser() -> argparse.ArgumentParser:
    # No non-Flex override flag exists: every live OpenAI request must use the Flex
    # service tier, enforced unconditionally at the provider call boundary
    # (OpenAIProvider.generate) with no override mechanism of any kind. See
    # docs/COST_CONTROL.md.
    parser = argparse.ArgumentParser(prog="coding-orchestrator")
    parser.add_argument("--config", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run")
    run.add_argument("--task", required=True)

    run_all = sub.add_parser("run-all")
    run_all.add_argument("--tasks-dir", required=True)

    sub.add_parser("validate")
    sub.add_parser("report")
    # Lists pending local handoff artifacts (see docs/CHATGPT_HANDOFF_WORKFLOW.md).
    # Read-only and local -- makes no network call; uploading to a configured
    # rclone remote is a separate, explicit, human-triggered step.
    sub.add_parser("handoff")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    engine = WorkflowEngine(config)
    if args.command == "run":
        state = engine.run_task_file(Path(args.task))
        print(state.model_dump_json(indent=2))
        return 0 if state.final_status == "completed" else 1
    if args.command == "run-all":
        states = engine.run_all(Path(args.tasks_dir))
        print(json.dumps([state.model_dump(mode="json") for state in states], indent=2))
        return 0 if all(state.final_status in {"completed", "skipped"} for state in states) else 1
    if args.command == "validate":
        results = engine.limits.enforce_validation_output(  # noqa: SLF001
            engine._validate(task=TaskSpec(id="manual", title="Manual validation"))
        )
        print(json.dumps([result.model_dump() for result in results], indent=2))
        return 0 if all(result.passed for result in results) else 1
    if args.command == "report":
        report_states = engine.state_store.load_all()
        payload = {
            "states": {key: value.model_dump(mode="json") for key, value in report_states.items()},
            "budget": engine.budget_report().model_dump(mode="json"),
            "convergence": engine.convergence_report(),
        }
        print(json.dumps(payload, indent=2))
        return 0
    if args.command == "handoff":
        records = list_handoffs(engine.handoff_builder.output_dir)
        print(json.dumps(records, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
