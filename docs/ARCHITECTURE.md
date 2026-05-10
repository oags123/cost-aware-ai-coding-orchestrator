# Architecture

The orchestrator is a deterministic control loop around bounded model assistance.

## Main Flow

`request -> classify -> route -> build context -> execute bounded step -> validate -> retry/escalate -> log result`

## Key Modules

- `coding_orchestrator/app.py` - CLI entrypoint.
- `coding_orchestrator/config.py` - Pydantic config models and YAML loading.
- `coding_orchestrator/schemas.py` - task, state, validation, command, patch, and escalation schemas.
- `coding_orchestrator/orchestrator/engine.py` - core workflow engine.
- `coding_orchestrator/orchestrator/router.py` - task classification and workflow selection.
- `coding_orchestrator/models/router.py` - model tier routing.
- `coding_orchestrator/tools/opencode_runner.py` - dry-run and real OpenCode runner.
- `coding_orchestrator/tools/patch.py` - strict output parsing and safe patch application.
- `coding_orchestrator/tools/git.py` - checkpoint, rollback, diff, status, commit.
- `coding_orchestrator/validators/` - deterministic validation gates.
- `coding_orchestrator/observability/` - JSONL logs, metrics, traces, audit wrappers.
- `coding_orchestrator/cache/` - hash cache.
- `coding_orchestrator/memory/` - simple short-term and project facts storage.

## Engine Behavior

For each task, `WorkflowEngine`:

1. Creates an `OrchestratorState`.
2. Captures a git checkpoint.
3. Classifies complexity, risk, task type, and workflow.
4. Selects a model tier.
5. Builds compact workflow context.
6. Calls `OpenCodeRunner`.
7. Parses and applies a patch in real mode.
8. Runs validators.
9. Retries with validator feedback if needed.
10. Commits scoped allowed files on success.
11. Rolls back and escalates on failure.

## Design Boundaries

The model does not choose policy, approve unsafe actions, or execute shell commands directly. Deterministic Python code controls command execution, validation, patch application, rollback, and logging.

