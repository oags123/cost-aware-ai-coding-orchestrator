# User Guide

## Operating modes

- Fake provider mode for deterministic local testing.
- OpenAI provider mode for real model calls (env-key only).

## Typical workflow

1. Create a bounded task file (`allowed_files`, budget/runtime limits, validation commands).
2. Run orchestrator.
3. Review `report` output for budget, convergence, and task states.
4. Escalate only when convergence or policy gates require it.

## Safety expectations

- Provider output cannot run shell commands.
- Patch application and validators are mandatory gates.
- Rollback happens on failure paths.
