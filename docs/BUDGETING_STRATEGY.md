# Budgeting Strategy

Status: planning only.

## Current State

The MVP has approximate cost estimates and in-memory project spend. This is enough for dry-run and early local testing but not enough for real cost governance.

## Phase 1.5 Target

Budget controls should become persistent, model-aware, and pre-call enforced.

## Budget Types

- task budget
- attempt budget
- project budget
- expensive-model budget
- escalation pool
- daily/session cap

## Proposed Data Sources

- static model pricing config for estimates
- actual provider usage when available
- persisted spend ledger for cross-run enforcement

## Proposed Config

```yaml
pricing:
  models:
    provider/model:
      input_usd_per_1m_tokens: 0.10
      output_usd_per_1m_tokens: 0.40

budget:
  max_task_cost_usd: 0.10
  max_attempt_cost_usd: 0.03
  max_project_cost_usd: 5.00
  max_expensive_cost_per_task_usd: 0.25
  max_expensive_calls_per_task: 1
```

## Required Tests

- blocks call when projected task budget is exceeded
- blocks call when project budget is exceeded
- blocks expensive call count above cap
- persists spend across CLI runs
- records budget-blocked state

