# Roadmap

This roadmap reflects the current implementation after Phase 1.5 Step 7A.
It documents future work only; these items are not runtime behavior unless
marked complete.

## Completed

- Phase 1 MVP controlled workflow engine.
- Real OpenCode runner path, disabled by default and gated by config.
- Safe patch parsing/application with file, delete, forbidden path, and size checks.
- Git checkpoint, rollback, and scoped commits.
- Persistent SQLite budget ledger and pre-call cost estimation.
- Hard token, context, output, patch, stdout/stderr, and validation output limits.
- Gemini Flex/Standard cheap-builder tier policy with bounded Standard fallback.
- Convergence/divergence attempt metrics and diagnosis-needed packages.
- Diagnosis-only expensive reviewer interface, disabled/dry-run by default.
- Step 7A: Telegram blocker/stop alerts, disabled by default.
- Future SafeAuto documented as a planning concept only.

## Current Implemented State

The orchestrator can run local dry-run tasks, enforce deterministic validation,
estimate cost before model/OpenCode calls, apply bounded patches in real
OpenCode mode, roll back failures, and notify Telegram on blocker/stop
conditions when configured.

Provider billing remains estimated, real reviewer/provider APIs are not wired,
and unattended queue continuation is not implemented.

## Recommended Order

1. Run one controlled real OpenCode/Gemini trial.
2. Step 8: add external watchdog and heartbeat.
3. Step 9: add robust persistent run/task state and resume.
4. Step 10: add integration checkpoints.
5. Step 11: formalize caching strategy.
6. Step 12: add a spec-to-tasks planner.
7. Add provider usage accounting when providers expose usable token/cost data.
8. Add memory/retrieval and richer observability only after state/resume is solid.

## Step 8: External Watchdog And Heartbeat

Add an independent watchdog process that monitors an orchestrator heartbeat.
It must work even if the orchestrator process crashes.

The watchdog should alert when:

- the orchestrator process dies
- heartbeat updates stall
- no task progress occurs within a configured window
- logs/state indicate a blocked or crashed run

Telegram is the initial alert channel. The watchdog should be separate from
the orchestrator process so it can still send alerts after a crash.

## Step 9: Robust Persistent Run/Task State

Move task/run state from append-only JSON into SQLite-backed state with exact
stage tracking.

Planned capabilities:

- run records with status, started/finished timestamps, and heartbeat metadata
- task records with current stage, final status, dependency status, and attempt count
- attempt history with validation, budget, limit, model, and rollback events
- blocked/completed/skipped persistence across process restarts
- `resume` command for crash/restart recovery
- safe reconciliation with Git state after interruption

This should come before unattended SafeAuto.

## Step 10: Integration Checkpoints

Add validation gates across queue execution, not just per-task validation.

Planned checkpoints:

- run module/integration validation every N completed tasks
- milestone validation gates after configured task groups
- final end-to-end validation before declaring a run successful
- automatic creation of integration-fix task files when checkpoints fail
- blocking behavior when checkpoint failures are severe or non-converging

## Step 11: Caching Strategy

Define a local cache for deterministic artifacts:

- built context
- summaries
- validation outputs
- review packets
- compact retry feedback

Future provider context caching can be added when prompts stabilize, but it
must remain an optimization only. Provider cache must not be the source of
truth for task state, budget accounting, validation results, or recovery.

## Step 12: Spec-To-Tasks Planner

Add a separate planning layer before the coding orchestrator.

The planner should convert `PROJECT_SPEC`, PRD, architecture, or design docs
into many small task files. It should include:

- task review and deduplication
- dependency validation
- allowed file suggestions
- risk and complexity classification
- validation command suggestions
- planner output review before execution

The likely model split is expensive-model planning/review and cheap-model task
expansion. The coding orchestrator should still execute tasks with the existing
controlled workflow.

## Future: Unattended SafeAuto

SafeAuto remains a future orchestrator policy, not an OpenCode, Gemini, or
OpenAI feature.

The intended behavior:

- auto-continue safe, bounded, converging tasks
- block unsafe, divergent, over-budget, or over-limit tasks
- continue independent runnable tasks when one task blocks
- send Telegram alerts only on real blockers, no progress, stalled heartbeat,
  or required human attention
- keep OpenCode permissions separate from orchestrator governance

Do not implement SafeAuto before watchdog, robust state, and resume exist.

## Future: Real OpenCode/Gemini Trial

Before broader real-mode use:

1. Install and authenticate OpenCode.
2. Enable `opencode.enabled=true` and `opencode.dry_run=false`.
3. Use one tiny task with narrow `allowed_files`.
4. Run from a clean branch or clone.
5. Document transcript, cost estimate, observed behavior, patches, validation,
   rollback/commit behavior, and issues.

## Future: Provider Usage Accounting

When providers expose usable usage data:

- ingest actual input/output token counts
- ingest actual cost if available
- reconcile estimated vs actual cost in the ledger
- report estimation error by provider/model/tier
- keep pre-call estimation as the hard gate before calls

## Future: Memory And Retrieval

Do not add embeddings/RAG/vector databases yet. Future memory should start
with deterministic local artifacts:

- project facts
- module summaries
- episodic attempt memory
- procedural memory for validated repair patterns
- retrieval for relevant files/snippets

Any retrieval layer must stay bounded by task file permissions and context
limits.

## Future: Observability

Improve operator visibility after persistent state exists:

- richer run reports
- timeline of attempts
- replay/debug views from logs/state
- task graph and status summaries
- budget/tier/limit/convergence dashboards as static reports, not a web UI

## What Not To Implement Yet

- unattended SafeAuto runtime behavior
- Telegram approval modes
- GPT/frontier direct patching
- reviewer model production API calls
- LangChain, LangGraph, CrewAI, AutoGen
- web UI or dashboards
- cloud deployment or Kubernetes
- semantic memory, embeddings, RAG, or vector DB
