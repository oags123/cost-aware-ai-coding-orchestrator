# AGENTS.md

## Current runtime status

This repository is a pure Python orchestrator with role/provider model execution.

Implemented:
- typed task/orchestrator state via Pydantic
- YAML config, always resolved relative to `repo_path`, never the caller's CWD
- SQLite budget ledger (pre-call estimates *and* reconciled actual token usage/cost,
  written idempotently) and JSON state/logs
- bounded workflow loop: classify -> route -> build context -> model step -> validate ->
  retry/escalate, with distinct terminal statuses (`completed`, `dry_run`, `no_change`,
  `blocked`, `escalated`, `failed`, `timeout`, `skipped`) — a disabled/misconfigured
  provider or a no-op builder response is never reported as `completed`
- strict Flex-only service-tier policy: every automatically routed call requests
  `flex`, enforced by a config-load-time validator (`AppConfig._enforce_flex_only_policy`)
  with no automatic fallback tier anywhere in the code; typed transient-error
  classification (`ProviderTransientError`) drives bounded, Flex-only retries
- OpenAI provider (env-key only, opt-in runtime via `providers.openai.runtime_enabled`),
  with real SDK exceptions mapped to typed provider errors rather than left unguarded
- fake provider path for tests/no-network runs
- patch contract parsing and boundary validation: forbidden paths, workspace escape,
  absolute paths, symlink creation, and declared-vs-actual path mismatches are all rejected
- structured builder output is strictly validated against the patch contract schema and
  rejected (not silently downgraded) if invalid
- `git apply --check`, patch apply, validator run, rollback, and scoped commit — commits
  only ever stage files that are both actually changed *and* in `task.allowed_files`
- stash-based checkpoint/rollback: any pre-existing uncommitted work in the target repo is
  preserved exactly, whether the task succeeds, fails, or is rolled back
- HEAD-change detection between checkpoint and commit
- advisory file-lock preventing concurrent runs against the same repository
- convergence tracking and diagnosis-only reviewer flow (dry-run/placeholder only — see
  Known Limitations)
- CI (`.github/workflows/ci.yml`) runs ruff/mypy/pytest/import-smoke/report-smoke on every
  push and PR

## Known limitations / intentionally not implemented

- The diagnosis/reviewer escalation path has no live model integration; it is always
  dry-run/placeholder (`diagnosis.dry_run: true` by default, and `diagnosis.enabled=false`
  by default). Do not represent it as a working escalation model to end users.
- Only the OpenAI provider is implemented. The `ModelProvider` interface is
  provider-agnostic in shape, but no other backend exists.
- `small_refactor`, `large_refactor`, `architecture_review`, `dependency_update`, and
  `security_review` workflows are defined but `Workflow.enabled=False`; tasks classified
  into them are routed to `requires_human_approval` (`blocked`) rather than executed.
- If a builder's patch fails to parse (`PatchContractError`) or apply
  (`PatchApplyError`)/fails structured-output validation (`StructuredOutputError`) on an
  attempt, that attempt aborts the task immediately rather than feeding into the normal
  validation-failure retry loop.

## Hard safety rules

- No model-generated shell execution.
- No hosted shell/apply-patch tool enablement.
- Deterministic tools run via subprocess wrappers with allowlists and timeouts.
- Validators remain mandatory after patch application.
- Rollback/git checkpointing remain mandatory on failure paths, and must preserve any
  pre-existing uncommitted work in the target repository exactly.
- Runtime, retries, context, output, and cost remain bounded.
- Only one orchestrator run may execute against a given repository at a time.

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
