# Cost Control Specification

Status: planning only.

## Optimization Target

Minimize expensive-model token usage while maintaining task quality and safety.

## Hard Controls

Design controls for:

- max expensive-model calls per task
- max expensive-model cost per task
- max expensive-model input tokens
- max expensive-model output tokens
- max context chars
- max patch bytes
- max stdout/stderr chars
- max review packet chars
- escalation budget pools
- persistent project spend tracking
- pre-call cost estimation

## Pre-Call Estimation

Before any paid or expensive model call:

1. Count/estimate input tokens.
2. Estimate output token cap.
3. Look up model pricing.
4. Compute projected cost.
5. Compare against task, escalation, and project budgets.
6. Block or require approval if projected spend exceeds limits.

## Proposed Budget Ledger

Persist spend events to JSON or SQLite:

```json
{
  "request_id": "uuid",
  "task_id": "T-042",
  "model_role": "expensive_reviewer",
  "model": "provider/model",
  "estimated_input_tokens": 4000,
  "estimated_output_tokens": 1000,
  "estimated_cost_usd": 0.12,
  "actual_cost_usd": null,
  "created_at": "ISO-8601"
}
```

## Proposed Config

```yaml
budget:
  max_task_cost_usd: 0.10
  max_project_cost_usd: 5.00
  max_expensive_cost_per_task_usd: 0.25
  max_expensive_calls_per_task: 1
  max_escalation_pool_usd: 1.00
  require_approval_above_usd: 0.20
```

## Failure Behavior

If a pre-call estimate exceeds budget:

- do not call the model
- write a budget-blocked state
- include the projected spend and remaining budget
- escalate to human only if configured

