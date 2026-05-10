# Budgeting Strategy

Status: Step 1 implemented for SQLite ledger and pre-call estimates.

## Current State

The MVP now has approximate cost estimates plus persistent SQLite spend tracking. It still does not ingest provider-reported actual usage.

## Phase 1.5 Target

Budget controls are persistent, model-role aware, and pre-call enforced for the current builder call path.

## Budget Types

Implemented:

- task budget
- project budget
- cheap builder budget pool
- expensive reviewer budget pool
- emergency budget pool reporting

Still planned:

- attempt budget
- expensive call count cap
- daily/session cap
- actual usage reconciliation

## Proposed Data Sources

- static model pricing config for estimates
- persisted SQLite spend ledger for cross-run enforcement
- actual provider usage when available in future

## Proposed Config

```yaml
pricing:
  models:
    provider/model:
      input_usd_per_1m_tokens: 0.10
      output_usd_per_1m_tokens: 0.40

budget:
  max_task_cost_usd: 0.10
  ledger_path: "logs/budget.sqlite"
  project_id: "default"
  project_total_budget_usd: 5.00
  cheap_builder_budget_usd: 3.00
  expensive_reviewer_budget_usd: 1.00
  emergency_budget_usd: 1.00
```

## Required Tests

Implemented:

- ledger persistence
- estimate calculation
- blocked call when projected task budget is exceeded
- role-specific pool enforcement
- project budget persistence across engine instances

Still needed:

- expensive call count cap
- actual usage reconciliation
- emergency pool behavior
