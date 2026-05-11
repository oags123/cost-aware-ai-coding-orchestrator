# Cost Control Specification

Status: Phase 2.5 catalog refresh completed for OpenAI role defaults, service tiers,
and pricing metadata.

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
- Gemini Flex as the default cheap builder tier
- controlled Gemini Standard fallback after Flex timeout policy triggers
- per-run Standard fallback count and cost caps
- report fields for calls/cost by tier, Flex timeouts, and Standard fallbacks
- attempt metrics for validator errors, failing tests, patch size, stream size, and changed files
- convergence/stagnation/divergence decisions before spending more cheap-builder retries
- `diagnosis_needed` package generation when cheap retries stop improving
- expensive reviewer per-call cost cap
- expensive reviewer max calls per task and per run
- expensive reviewer budget-pool enforcement before diagnosis calls

Still planned:

- max expensive-model calls per task
- max review packet chars
- emergency budget behavior beyond reporting

## Cheap Retry Cost Control

Convergence evaluation is part of cost control. The orchestrator continues
cheap retries only while deterministic metrics show improvement or remain
within configured thresholds. It stops cheap retries and creates a
`diagnosis_needed` package when attempts stagnate or diverge.

```yaml
convergence:
  max_stagnant_attempts: 2
  max_divergent_attempts: 1
  max_patch_growth_ratio: 1.5
  max_failure_growth_ratio: 1.25
  min_improvement_score_to_continue: -1.0
  hard_stop_on_syntax_regression: true
  hard_stop_on_unrelated_file_touch: true
```

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

## OpenAI Service Tiers

Non-urgent builder roles default to Flex where supported and fall back to
Default when Flex timeouts or resource unavailability repeat.

```yaml
policies:
  service_tiers:
    budget_optimization_enabled: true
    default_builder_tier: "flex"
    fallback_builder_tier: "default"
    priority_enabled: false
    max_flex_timeouts_before_fallback: 2
    max_priority_cost_usd_per_run: 0.0
```

Flex behavior follows OpenAI docs:
- lower cost, slower response, occasional 429 resource unavailable
- increase request timeout for Flex workloads
- fallback to `default` when Flex retries/timeouts exceed policy
- record actual `service_tier` returned by API when available

Priority remains disabled by default and requires explicit policy + budget approval.

Pricing stays config-driven and includes source metadata and verification date:

```yaml
pricing:
  roles:
    general_builder:flex:
      provider: "openai"
      model: "gpt-5.4-mini"
      service_tier: "flex"
      input_usd_per_1m_tokens: 0.375
      cached_input_usd_per_1m_tokens: 0.0375
      output_usd_per_1m_tokens: 2.25
      max_output_tokens: 6000
      budget_pool: "builder"
      source_url: "https://developers.openai.com/api/docs/pricing"
      retrieved_or_verified_date: "2026-05-11"
```

Frontier/pro roles are diagnosis/review-only by default and do not become automatic builders.

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
  "inference_tier": "flex",
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
      provider: "google-gemini"
      model: "gemini-3.1-flash-lite"
      input_usd_per_1m_tokens: 0.125
      output_usd_per_1m_tokens: 0.75
      max_output_tokens: 4000
      budget_pool: "cheap_builder"
```

Sample prices are placeholders and must be audited before real paid usage.

## Expensive Reviewer Controls

The expensive reviewer is diagnosis-only and disabled by default:

```yaml
diagnosis:
  enabled: false
  provider: "placeholder"
  model: "frontier-reviewer-placeholder"
  max_input_tokens: 8000
  max_output_tokens: 1500
  max_context_chars: 24000
  max_cost_per_call_usd: 0.25
  max_calls_per_task: 1
  max_calls_per_run: 2
  role_budget_pool: "expensive_reviewer"
  diagnosis_only: true
  allow_direct_patch: false
```

Before any enabled reviewer call, the orchestrator estimates tokens/cost, checks
the expensive reviewer budget pool, and enforces per-task/per-run call caps. If
any check fails, it creates a `diagnosis_needed` package and does not call the
reviewer.

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
