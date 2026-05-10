# Phase 1.5 Architecture Plan

Status: planning only. Do not treat this as implemented behavior.

## Goal

Phase 1.5 evolves the MVP from "bounded local OpenCode execution" into a cost-aware, multi-tier control system that maximizes cheap automated coding while minimizing expensive-model usage.

The expensive model must never become the default coder.

## Role Model

- Cheap model: builder, executor, distiller.
- Expensive model: diagnosis, review, architecture, risk analysis.
- Orchestrator: controller and judge.
- Validators: objective truth system.
- Human: final escalation layer.

## Default Policy

`allow_frontier_direct_patch = false`

Direct expensive-model patch generation should remain disabled by default. If ever added, it must require explicit human approval and a budget override.

## Proposed Control Loop

1. Run cheap builder attempt.
2. Apply patch only through existing patch contract.
3. Run validators.
4. Measure convergence/divergence.
5. If converging, continue cheap retry within limits.
6. If ambiguous, use cheap model to distill context.
7. If escalation criteria are met, send compact review packet to expensive model for diagnosis only.
8. Feed expensive diagnosis back to cheap model as repair guidance.
9. Escalate to human if budget/runtime/divergence limits are exceeded.

## Phase Boundaries

Phase 1.5 should not add:

- LangChain, LangGraph, CrewAI, AutoGen
- web UI
- semantic memory
- embeddings/RAG/vector DB
- provider marketplace
- direct expensive-model coding by default

## Proposed Implementation Phases

1. Add config/schema proposals for model roles, token limits, and escalation budgets.
2. Add persistent budget ledger and pre-call cost estimation.
3. Add convergence/divergence scoring from validator history.
4. Add cheap distillation/review packet generation.
5. Add expensive diagnosis-only interface.
6. Add human/Telegram escalation planning and manual approval gates.
7. Trial with one real OpenCode task and one diagnosis-only escalation.

## Migration Strategy

Keep the current Phase 1 dry-run and OpenCode real-mode paths intact. Add Phase 1.5 controls around them rather than replacing them.

No existing task files should need migration except optional new fields for budgets, token caps, escalation policy, and model-role overrides.

