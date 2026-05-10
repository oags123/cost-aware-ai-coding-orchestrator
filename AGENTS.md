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
- persistent SQLite budget ledger and pre-call cost estimation
- hard token, context, output, patch, stdout/stderr, and validation output limits
- Gemini Flex/Standard cheap builder tier policy with bounded Standard fallback
- convergence/divergence attempt metrics with diagnosis-needed escalation packages
- diagnosis-only review packet builder and dry-run reviewer interface
- expensive reviewer diagnosis contract, budget gates, and call limits
- Telegram blocker/stop alerts, disabled by default
- unit tests for core safety and workflow paths

Placeholder or intentionally limited:
- Codex/Claude reviewer integrations are placeholders only
- budget accounting is estimated, not provider-reported
- dry-run builder output is mock output
- workflows beyond `explain_code`, `fix_bug`, and `write_tests` are scaffolded
- no direct Gemini API integration exists; Gemini model/tier policy is config and OpenCode-path routing only
- unattended SafeAuto is documented as a future idea only

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

Phase 1.5 planning docs have been added under `docs/`. Steps 1-7A have been
implemented:
- persistent SQLite budget ledger and pre-call cost estimation
- hard token/context/output/patch/stdout/stderr/validation-output limits
- Gemini Flex default builder tier with controlled Standard fallback
- deterministic convergence/divergence metrics for cheap retries
- diagnosis-only review packet interface, dry-run by default
- diagnosis-only expensive reviewer interface with structured guidance for cheap retries
- Telegram blocker/stop alerts, disabled by default

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

Implemented Phase 1.5 Step 2 files:
- `coding_orchestrator/orchestrator/limits.py`
- `tests/test_limits.py`
- related wiring in `coding_orchestrator/orchestrator/engine.py`

Implemented Phase 1.5 Step 3 files:
- `coding_orchestrator/orchestrator/tier_policy.py`
- `tests/test_tier_policy.py`
- tier-aware budget ledger/report wiring in `coding_orchestrator/orchestrator/budget.py`

Implemented Phase 1.5 Step 4 files:
- `coding_orchestrator/orchestrator/convergence.py`
- `tests/test_convergence.py`
- attempt metric state fields in `coding_orchestrator/schemas.py`
- retry-loop decision wiring in `coding_orchestrator/orchestrator/engine.py`

Implemented Phase 1.5 Step 5 files:
- `coding_orchestrator/orchestrator/diagnosis.py`
- `tests/test_diagnosis.py`
- review packet and diagnosis result schemas in `coding_orchestrator/schemas.py`
- diagnosis-only wiring in `coding_orchestrator/orchestrator/engine.py`

Implemented Phase 1.5 Step 6 behavior:
- reviewer config for provider/model/token/context/cost/call limits
- diagnosis-only response contract validation
- rejection of diffs, shell commands, file writes, large code blocks, and direct patches
- expensive reviewer budget and per-task/per-run call gates
- guided cheap retry using only `gemini_instruction` and compact diagnosis summary

Implemented Phase 1.5 Step 7A behavior:
- Telegram config fields and example config
- environment-only bot token and chat id
- notification-only blocker/stop alerts
- no approval modes, no SafeAuto runtime behavior, and no model permission changes
- future SafeAuto planning doc

Current budget behavior:
- pricing is config-driven by model role
- pre-call estimates are made from actual context before model/OpenCode calls
- task, role-pool, and project budgets can block calls
- ledger entries are persisted to SQLite
- CLI `report` includes budget usage and blocked call count

Current limit behavior:
- context/input/output limits are checked before OpenCode/model calls
- retry feedback is truncated to configured chars
- builder stdout/stderr and patch byte limits are checked after builder output
- validation output is truncated by default, or rejected if configured
- CLI `report` includes limit failures and largest tracked context/output sizes

Current tier behavior:
- cheap builder defaults to Gemini Flex
- current documented stable cheap model default is `gemini-3.1-flash-lite`
- Standard fallback is allowed only after Flex timeout policy triggers
- Standard fallback is capped by per-run count and estimated cost
- builder work must not fall back to GPT-5.5 or other frontier models
- CLI `report` includes calls/cost by tier, Flex timeouts, and Standard fallbacks

Current convergence behavior:
- every attempt records validation status, failing test count, validator error count, changed file count, patch size, stream sizes, failure categories, repeated failures, and new failures
- convergence/stagnation/divergence is deterministic and config-driven
- hard stops can trigger on syntax regression or unrelated file touches
- non-converging tasks create `diagnosis_needed` escalation packages
- diagnosis packages include compact review packets
- optional diagnosis dry-run records structured placeholder guidance
- enabled diagnosis can feed bounded guidance into the next cheap-builder retry
- no real GPT/reviewer API call is implemented yet
- direct expensive-model patches remain disabled by policy

Current Telegram behavior:
- alerts are disabled by default
- bot token and chat id are read from environment variables only
- token and chat id must never be hardcoded in repo files
- alerts cover blocker/stop conditions such as blocked tasks, budget exhaustion, runtime exhaustion, no runnable tasks, system errors, and escalation
- Telegram is notification-only; it does not approve, resume, or change runs

Current operator setup docs:
- `docs/USER_GUIDE.md` is the owner/operator setup guide for the current MVP
- `docs/REAL_WORLD_TRIAL.md` is the first real OpenCode runbook
- `docs/OPENCODE_SETUP.md` is the canonical OpenCode/Gemini setup guide
- `docs/OPEN_CODE_SETUP.md` is a compatibility pointer only
- Docker is optional and is not the recommended first real OpenCode trial path because the current Dockerfile does not install OpenCode or provider credentials

Future SafeAuto status:
- `safe_auto` / `unattended_safe_auto` is not implemented
- the future concept is documented in `docs/FUTURE_UNATTENDED_SAFE_AUTO.md`
- SafeAuto would be orchestrator policy, not a Google, OpenAI, or OpenCode feature
- OpenCode permissions remain separate from orchestrator governance

Pending roadmap order:
1. Real OpenCode/Gemini trial with one tiny, narrow task.
2. Step 8: external watchdog and heartbeat.
3. Step 9: robust SQLite run/task state and `resume`.
4. Step 10: integration checkpoints and integration-fix task creation.
5. Step 11: local caching strategy, with provider cache only as an optimization.
6. Step 12: spec-to-tasks planner before the coding orchestrator.
7. Provider usage accounting when actual token/cost data is available.
8. Memory/retrieval and richer observability after persistent state is stable.

## Coding standards for this repo

- Use plain Python and local helper APIs.
- Keep state typed with Pydantic.
- Keep config in YAML.
- Use subprocess wrappers with timeouts.
- Keep retries, runtime, and cost bounded.
- Add tests for safety boundaries and failure paths.
- Do not hardcode API keys, tokens, or secrets.
- Do not introduce LangChain, LangGraph, CrewAI, AutoGen, dashboards, embeddings, RAG, vector databases, or cloud deployment without explicit approval.
