# Cost Control Specification

Status: Step 1 and Step 2 implemented for persistent budget ledger, pre-call
estimation, and hard token/context/output/patch/stdout limits.

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
- hard input-token and output-token caps before OpenCode/model calls
- hard context character cap before OpenCode/model calls
- retry feedback truncation
- patch byte cap before safe patch application
- stdout/stderr byte caps after builder execution
- validation output truncation or rejection
- report fields for limit failures and largest tracked context/output sizes

Still planned:

- max expensive-model calls per task
- max review packet chars
- emergency budget behavior beyond reporting

## Pre-Call Estimation

Before any model/OpenCode call:

1. Count/estimate input tokens.
2. Use configured role max output tokens.
3. Look up model pricing.
4. Compute projected cost.
5. Check context, input token, and configured output token limits.
6. Compare against task, role pool, and project budgets.
7. Block the call if projected spend or hard limits are exceeded.

## Hard Limits

Configured limits:

```yaml
limits:
  max_input_tokens_per_call: 32000
  max_output_tokens_per_call: 4000
  max_context_chars_per_call: 128000
  max_retry_context_chars: 8000
  max_patch_bytes: 256000
  max_stdout_bytes: 256000
  max_stderr_bytes: 64000
  max_validation_output_bytes: 64000
  context_over_limit_policy: "reject"
  output_over_limit_policy: "reject"
  validation_output_over_limit_policy: "truncate"
```

Failure statuses:

- `context_limit_exceeded`
- `output_limit_exceeded`
- `patch_limit_exceeded`
- `validation_output_limit_exceeded`

Context and output limits are enforced before OpenCode is invoked. Builder
stdout/stderr and patches are checked after execution but before patch
application. Validation output is either truncated or converted to a failed
validation result, depending on config.

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
  "estimated_context_chars": 16000,
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

If a hard limit is exceeded:

- do not call the model when the failure is known pre-call
- do not apply the patch when patch/output limits are exceeded post-call
- write a blocked task state for pre-call/builder/patch limit failures
- record the limit status in the budget ledger when a call estimate exists
- include limit counters and largest tracked sizes in `report`
