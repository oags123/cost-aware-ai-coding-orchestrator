# Budgeting Strategy

Status: Step 1 and Step 2 implemented for SQLite ledger, pre-call estimates,
and hard token/context/output size limits.

## Current State

The MVP now has approximate cost estimates, persistent SQLite spend tracking,
and hard size gates before and after the builder call. It still does not ingest
provider-reported actual usage.

## Phase 1.5 Target

Budget controls are persistent, model-role aware, and pre-call enforced for the current builder call path.

## Budget Types

Implemented:

- task budget
- project budget
- cheap builder budget pool
- expensive reviewer budget pool
- emergency budget pool reporting
- pre-call input token cap
- pre-call output token cap
- context char cap
- retry feedback char cap
- patch byte cap
- stdout/stderr byte caps
- validation output byte cap

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

limits:
  max_input_tokens_per_call: 32000
  max_output_tokens_per_call: 4000
  max_context_chars_per_call: 128000
  max_retry_context_chars: 8000
  max_patch_bytes: 256000
  max_stdout_bytes: 256000
  max_stderr_bytes: 64000
  max_validation_output_bytes: 64000
```

## Required Tests

Implemented:

- ledger persistence
- estimate calculation
- blocked call when projected task budget is exceeded
- role-specific pool enforcement
- project budget persistence across engine instances
- context too large blocks call
- output token estimate too large blocks call
- patch too large rejected
- stdout/stderr too large handled safely
- validation output too large handled safely
- budget ledger records limit-blocked calls

Still needed:

- expensive call count cap
- actual usage reconciliation
- emergency pool behavior
