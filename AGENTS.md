# AGENTS.md

## Current runtime status

This repository is a pure Python orchestrator with role/provider model execution.

Implemented:
- typed task/orchestrator state via Pydantic
- YAML config
- SQLite budget ledger and JSON state/logs
- bounded workflow loop: classify -> route -> build context -> model step -> validate -> retry/escalate
- role-based model routing and service-tier policy
- OpenAI provider (env-key only, opt-in runtime)
- fake provider path for tests/no-network runs
- patch contract parsing and boundary validation
- `git apply --check`, patch apply, validator run, rollback, and scoped commit
- convergence tracking and diagnosis-only reviewer flow

## Hard safety rules

- No model-generated shell execution.
- No hosted shell/apply-patch tool enablement.
- Deterministic tools run via subprocess wrappers with allowlists and timeouts.
- Validators remain mandatory after patch application.
- Rollback/gif checkpointing remain mandatory on failure paths.
- Runtime, retries, context, output, and cost remain bounded.

## Model role philosophy

- Orchestrator controls policy and routing.
- Validators are objective truth.
- Use the lowest-cost role with reasonable validation success probability.
- Escalate only on convergence failure, risk, ambiguity, or policy limits.
- Frontier reviewer roles are diagnosis-first by default.

## Standard validation commands

- `.venv/bin/ruff check .`
- `.venv/bin/mypy .`
- `.venv/bin/pytest`
