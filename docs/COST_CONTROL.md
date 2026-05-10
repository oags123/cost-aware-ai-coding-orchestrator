# Cost Control Specification

Status: Step 1 implemented for persistent budget ledger and pre-call estimation.

## Optimization Target

Minimize expensive-model token usage while maintaining task quality and safety.

## Hard Controls

Implemented controls:

- persistent SQLite budget ledger
- model-role pricing config
- pre-call token/cost estimate before model/OpenCode invocation
- task budget check
- role budget pool check
- project total budget check
- budget report with usage, remaining budget, and blocked calls

Still planned:

- max expensive-model calls per task
- max expensive-model input tokens
- max context chars
- max patch bytes
- max stdout/stderr chars
- max review packet chars
- emergency budget behavior beyond reporting

## Pre-Call Estimation

Before any model/OpenCode call:

1. Count/estimate input tokens.
2. Use configured role max output tokens.
3. Look up model pricing.
4. Compute projected cost.
5. Compare against task, role pool, and project budgets.
6. Block the call if projected spend exceeds limits.

## Budget Ledger

Spend events are persisted to SQLite:

```json
{
  "project_id": "default",
  "task_id": "T-042",
  "attempt_id": 1,
  "model_role": "expensive_reviewer",
  "provider": "placeholder",
  "model": "provider/model",
  "estimated_input_tokens": 4000,
  "estimated_output_tokens": 1000,
  "estimated_input_cost_usd": 0.02,
  "estimated_output_cost_usd": 0.10,
  "estimated_total_cost_usd": 0.12,
  "actual_input_tokens": null,
  "actual_output_tokens": null,
  "actual_cost_usd": null,
  "timestamp": "ISO-8601",
  "status": "estimated"
}
```

## Config

```yaml
budget:
  max_task_cost_usd: 0.10
  ledger_path: "logs/budget.sqlite"
  project_id: "default"
  project_total_budget_usd: 5.0
  cheap_builder_budget_usd: 3.0
  expensive_reviewer_budget_usd: 1.0
  emergency_budget_usd: 1.0

pricing:
  roles:
    cheap_builder:
      provider: "opencode"
      model: "opencode-local"
      input_usd_per_1m_tokens: 0.10
      output_usd_per_1m_tokens: 0.40
      max_output_tokens: 4000
      budget_pool: "cheap_builder"
```

Sample prices are placeholders and must be audited before real paid usage.

## Failure Behavior

If a pre-call estimate exceeds budget:

- do not call the model
- write a budget-blocked state
- include the projected spend and remaining budget
- record a blocked ledger event
