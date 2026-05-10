# MVP Status

## Complete Enough For Local Dry-Run Use

- CLI entrypoint
- task loading
- dependency ordering
- classification and routing
- dry-run builder execution
- validation pipeline
- retry loop
- logging and state files
- escalation package generation
- Docker scaffold
- Telegram blocker/stop alerts, disabled by default
- unit tests

## Complete But Needs Real-World Trial

- real OpenCode subprocess invocation
- strict patch parsing
- safe patch application
- git checkpoint/rollback
- scoped task commits
- Gemini Flex/Standard policy through the OpenCode builder path

These are implemented and tested with mocks/temp repositories, but should be exercised with one carefully scoped real OpenCode task before broader use.

## Placeholder

- reviewer/escalation model API integrations
- accurate provider billing/cost accounting
- specialized implementations for scaffolded workflows
- long-term memory beyond simple project facts storage
- unattended SafeAuto runtime behavior

## Deferred

- web UI
- cloud deployment
- Kubernetes
- Gemini/provider integrations
- embeddings/RAG/vector database
- multi-agent conversation systems
- Telegram approval modes

## Phase 1.5 Direction

Phase 1.5 is a cost-control and escalation-policy evolution, not a framework
rewrite. Steps 1-7A are implemented. The remaining roadmap is:

1. External watchdog and heartbeat.
2. Robust SQLite run/task state and `resume`.
3. Integration checkpoints.
4. Local caching strategy.
5. Spec-to-tasks planner.
6. Provider usage accounting.
7. Memory/retrieval and richer observability after persistent state is stable.

The proposed role split is:

- cheap model = builder/executor/distiller
- expensive model = diagnosis/review/architecture
- orchestrator = controller/judge
- validators = objective truth system
- human = final escalation layer

The default proposed policy is `allow_frontier_direct_patch = false`.

See [Roadmap](ROADMAP.md) and [Phase 1.5 Architecture](PHASE_1_5_ARCHITECTURE.md).
