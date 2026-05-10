# AGENTS.md

## Current implementation status

This repository now contains a usable local Phase 1 MVP.

Complete:
- typed task and orchestrator state with Pydantic
- YAML config and task files
- CLI commands: `run`, `run-all`, `validate`, `report`
- dependency ordering for task queues
- task classification, workflow selection, and model routing
- dry-run builder mode
- config-gated real OpenCode mode using `opencode run`
- strict patch contract and safe patch application
- validators for command safety, patch boundaries, permissions, syntax, and tests
- git checkpoint, rollback, scoped commit, diff, and status helpers
- bounded retry loop with validator feedback
- escalation package generation
- JSON state and JSONL logs
- Dockerfile and docker-compose
- unit tests for core safety and workflow paths

Placeholder or intentionally limited:
- Codex/Claude reviewer integrations are placeholders only
- budget accounting is estimated, not provider-reported
- dry-run builder output is mock output
- workflows beyond `explain_code`, `fix_bug`, and `write_tests` are scaffolded
- no Gemini/provider routing or pricing integration exists

## Project goal

Build Phase 1 of a Cost-Aware AI Coding Orchestrator.

This is a controlled workflow engine, not a free-roaming AI agent.

The orchestrator must control:
request → classify → route → build context → execute bounded step → validate → retry/escalate → log result.

## Hard rules

- Do not build a web UI.
- Do not build LangChain, LangGraph, CrewAI, or AutoGen integration in Phase 1.
- Use plain Python.
- Use typed state with Pydantic.
- Use YAML config.
- Use SQLite or JSON for persistent state.
- Use subprocess with timeouts for shell commands.
- Never allow unlimited retries.
- Never allow unlimited runtime.
- Never allow unlimited cost.
- Do not let LLMs execute arbitrary shell commands directly.
- The orchestrator runs deterministic tools itself: git, pytest, ruff, mypy.
- LLMs are only called inside bounded steps.

## OpenCode integration

OpenCode real mode is disabled by default:

```yaml
opencode:
  enabled: false
  dry_run: true
```

When enabled with `dry_run: false`, `coding_orchestrator/tools/opencode_runner.py` invokes `opencode run` with a bounded timeout. It expects only a unified diff or JSON containing `patch`, `touched_files`, `summary`, and `confidence`.

OpenCode output is parsed by `coding_orchestrator/tools/patch.py` and applied only after:
- file boundary validation
- forbidden path validation
- delete policy validation
- max changed file validation
- `git apply --check`

Do not add arbitrary shell execution for model output.

## Retry and escalation behavior

Retries are bounded by `TaskSpec.max_attempts`. Validator failures are compacted and included in the next builder prompt. When attempts are exhausted or escalation conditions apply, an escalation package is written under `logs/escalations/`.

Escalation packages are for manual/reviewer follow-up. No reviewer model API is integrated yet.

## Git and rollback behavior

Before each task the engine captures a `GitCheckpoint`. On failure or timeout it restores tracked/staged changes and removes untracked files created after the checkpoint, while preserving configured safe paths such as `logs/` and cache directories.

On success, commits stage only `task.allowed_files`. If there are no changes, the commit step is treated as no-op success. Commit failure fails the task.

## Phase 1 scope

Implement:
- task state
- task classifier
- model router
- workflow engine
- OpenCode runner interface and config-gated real execution
- Codex/Claude escalation interface as placeholders
- git manager
- validator runner
- patch/file boundary validator
- timeout guard
- budget guard
- logging
- CLI entrypoint

## Validation commands

Use:
- .venv/bin/ruff check .
- .venv/bin/mypy .
- .venv/bin/pytest

## Recommended next implementation priorities

1. Manually install/authenticate OpenCode and run one controlled real task in a clean clone or branch.
2. Add an integration test harness with a fake `opencode` executable that emits a patch.
3. Improve real-mode observability around OpenCode stdout/stderr and patch summaries.
4. Consider OpenCode `--format json` support if raw stdout parsing is brittle.
5. Add reviewer-model escalation only after real builder execution is proven stable.

## Phase 1.5 planning context

Phase 1.5 planning docs have been added under `docs/`. Step 1 has been implemented:
persistent SQLite budget ledger and pre-call cost estimation.

New architecture philosophy:
- cheap model = builder/executor/distiller
- expensive model = diagnosis/review/architecture
- orchestrator = controller/judge
- validators = objective truth system
- human = final escalation layer

Cost-first principles:
- minimize expensive-model token usage
- use cheap AI preprocessing/distillation before expensive calls
- send expensive models compact review packets, not raw repo dumps
- keep expensive models diagnosis-only by default
- default policy proposal: `allow_frontier_direct_patch = false`

Convergence/divergence concepts:
- continue cheap retries while tests/errors/diffs show convergence
- escalate when retries stagnate, diverge, exceed budget/runtime, or hit hard ceilings
- do not escalate merely because one retry failed

Planning docs:
- `docs/PHASE_1_5_ARCHITECTURE.md`
- `docs/MODEL_ROLES.md`
- `docs/COST_CONTROL.md`
- `docs/BUDGETING_STRATEGY.md`
- `docs/CONVERGENCE_LOGIC.md`
- `docs/ESCALATION_POLICY.md`
- `docs/REVIEW_PACKET_SPEC.md`
- `docs/TELEGRAM_ESCALATION.md`
- `docs/FUTURE_PROVIDER_INTEGRATION.md`

Do not implement Phase 1.5 runtime behavior until explicitly requested.

Implemented Phase 1.5 Step 1 files:
- `coding_orchestrator/orchestrator/budget.py`
- `coding_orchestrator/config.py`
- `tests/test_budget_ledger.py`

Current budget behavior:
- pricing is config-driven by model role
- pre-call estimates are made from actual context before model/OpenCode calls
- task, role-pool, and project budgets can block calls
- ledger entries are persisted to SQLite
- CLI `report` includes budget usage and blocked call count

## Coding standards for this repo

- Use plain Python and local helper APIs.
- Keep state typed with Pydantic.
- Keep config in YAML.
- Use subprocess wrappers with timeouts.
- Keep retries, runtime, and cost bounded.
- Add tests for safety boundaries and failure paths.
- Do not hardcode API keys, tokens, or secrets.
- Do not introduce LangChain, LangGraph, CrewAI, AutoGen, dashboards, embeddings, RAG, vector databases, or cloud deployment without explicit approval.
