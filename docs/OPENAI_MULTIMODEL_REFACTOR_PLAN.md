# OpenAI Multimodel Refactor Plan

Status: planning only. No runtime refactor has been implemented in this phase.

## 1. Current Architecture Summary

The repository is a Phase 1 local workflow engine:

- CLI entrypoint: `coding_orchestrator/app.py`
- main controller: `coding_orchestrator/orchestrator/engine.py`
- task classification: `coding_orchestrator/orchestrator/router.py`
- model string routing: `coding_orchestrator/models/router.py`
- builder execution: `coding_orchestrator/tools/opencode_runner.py`
- patch contract and safe application: `coding_orchestrator/tools/patch.py`
- deterministic validators: `coding_orchestrator/validators/*`
- git checkpoint, rollback, commit, diff, and status: `coding_orchestrator/tools/git.py`
- budget ledger and pre-call estimates: `coding_orchestrator/orchestrator/budget.py`
- context/output/patch/stream limits: `coding_orchestrator/orchestrator/limits.py`
- convergence metrics: `coding_orchestrator/orchestrator/convergence.py`
- diagnosis packet and dry-run reviewer interface: `coding_orchestrator/orchestrator/diagnosis.py`
- typed state and task schemas: `coding_orchestrator/schemas.py`
- YAML config schema: `coding_orchestrator/config.py`

The important safety properties already exist and must be preserved:

- Python owns orchestration and policy.
- Model output is never allowed to execute shell commands.
- Deterministic tools run through bounded subprocess wrappers.
- Patch output is parsed, boundary-checked, and verified with `git apply --check`.
- Validation runs after patch application.
- Failed attempts roll back to a git checkpoint.
- Commits stage only task-scoped files.
- Retries, runtime, cost, context, output, patch, stdout, stderr, and validation output are bounded.

## 2. Files And Modules That Reference OpenCode

OpenCode references were found in these files:

- `AGENTS.md`
- `README.md`
- `config.example.yaml`
- `coding_orchestrator/config.py`
- `coding_orchestrator/orchestrator/engine.py`
- `coding_orchestrator/orchestrator/escalation.py`
- `coding_orchestrator/tools/opencode_runner.py`
- `coding_orchestrator/tools/patch.py`
- `coding_orchestrator/models/local_model.py`
- `tests/test_opencode_and_patch.py`
- `tests/test_core.py`
- `tests/test_tier_policy.py`
- `docs/ARCHITECTURE.md`
- `docs/CONFIGURATION.md`
- `docs/COST_CONTROL.md`
- `docs/FUTURE_PROVIDER_INTEGRATION.md`
- `docs/FUTURE_UNATTENDED_SAFE_AUTO.md`
- `docs/MODEL_ROLES.md`
- `docs/MVP_STATUS.md`
- `docs/OPENCODE_SETUP.md`
- `docs/OPEN_CODE_SETUP.md`
- `docs/PHASE_1_5_ARCHITECTURE.md`
- `docs/QUICKSTART.md`
- `docs/REAL_WORLD_TRIAL.md`
- `docs/ROADMAP.md`
- `docs/SAFETY.md`
- `docs/TROUBLESHOOTING.md`
- `docs/USER_GUIDE.md`

Runtime OpenCode coupling is concentrated in:

- `OpenCodeSettings` in `coding_orchestrator/config.py`
- `OpenCodeRunner` and `OpenCodeExecutionError` in `coding_orchestrator/tools/opencode_runner.py`
- `WorkflowEngine._run_tiered_builder()` in `coding_orchestrator/orchestrator/engine.py`
- OpenCode-specific error text in `coding_orchestrator/orchestrator/escalation.py`
- the patch contract error message in `coding_orchestrator/tools/patch.py`

## 3. Files And Modules That Assume Cheap/Expensive Only

Cheap/expensive and Gemini tier assumptions were found in:

- `AGENTS.md`
- `config.example.yaml`
- `coding_orchestrator/config.py`
- `coding_orchestrator/orchestrator/budget.py`
- `coding_orchestrator/orchestrator/tier_policy.py`
- `coding_orchestrator/orchestrator/engine.py`
- `coding_orchestrator/orchestrator/diagnosis.py`
- `coding_orchestrator/orchestrator/convergence.py`
- `coding_orchestrator/schemas.py`
- `coding_orchestrator/models/cloud_model.py`
- `tests/test_budget_ledger.py`
- `tests/test_convergence.py`
- `tests/test_diagnosis.py`
- `tests/test_limits.py`
- `tests/test_telegram.py`
- `tests/test_tier_policy.py`
- `docs/BUDGETING_STRATEGY.md`
- `docs/CONVERGENCE_LOGIC.md`
- `docs/COST_CONTROL.md`
- `docs/ESCALATION_POLICY.md`
- `docs/FUTURE_PROVIDER_INTEGRATION.md`
- `docs/MODEL_ROLES.md`
- `docs/PHASE_1_5_ARCHITECTURE.md`
- `docs/REVIEW_PACKET_SPEC.md`
- `docs/TASKS.md`
- `docs/TELEGRAM_ESCALATION.md`

Key hardcoded concepts to replace:

- budget pools named `cheap_builder` and `expensive_reviewer`
- inference tiers named `flex` and `standard`
- Gemini model examples such as `gemini-3.1-flash-lite`
- diagnosis fields such as `gemini_instruction`
- convergence action `continue_cheap_retry`
- engine method `_run_tiered_builder`
- report fields `calls_by_tier`, `flex_timeouts`, and `standard_fallbacks`

## 4. Proposed New Architecture

Introduce a provider/model layer under `coding_orchestrator/models/`:

- `provider.py`
  - provider protocol or abstract base class
  - `ModelRequest`, `ModelResponse`, `ModelUsage`, `ModelRoleConfig`
  - provider errors such as `ProviderError`, `ProviderTimeout`, `StructuredOutputError`
- `openai_provider.py`
  - direct OpenAI Python SDK integration
  - reads `OPENAI_API_KEY` from environment only
  - uses the Responses API
  - supports structured builder and diagnosis output
  - returns text, parsed structured data when available, refusal/error status, usage tokens, and runtime metadata
- `fake_provider.py`
  - deterministic dry-run/test provider
  - emits configured builder or reviewer responses without network calls
- `router.py`
  - capability-role routing, not model-name routing
  - chooses a role such as `mechanical_worker`, `simple_builder`, `general_builder`, or `frontier_reviewer`
  - returns role plus reason and escalation intent

The engine should evolve from:

`task -> complexity/risk -> model string -> OpenCodeRunner -> parse patch`

to:

`task -> context/risk/validation/attempt metrics/budget -> model role -> provider call -> structured builder response -> parse patch -> validate/apply`

The orchestrator still owns all deterministic actions. OpenAI tools/function calls should be disabled by default for builder roles because shell/git/test execution remains under Python control. Function calling may be supported later only for explicitly safe, side-effect-free orchestration helpers.

## 5. New Config Schema

Replace `opencode`, `inference.cheap_builder`, fixed pricing roles, and cheap/expensive budgets with role/provider configuration.

Proposed YAML shape:

```yaml
providers:
  openai:
    enabled: true
    api_key_env_var: "OPENAI_API_KEY"
    base_url: null
    request_timeout_seconds: 300
    max_retries: 0

model_roles:
  mechanical_worker:
    provider: "openai"
    model_alias: "openai_nano"
    purpose: "tiny deterministic coding tasks"
    max_input_tokens: 16000
    max_output_tokens: 1500
    max_context_chars: 64000
    reasoning_effort: "none"
    verbosity: "low"
    structured_output: true
    allow_tools: false
    allow_direct_patch: true
    budget_pool: "worker"

  simple_builder:
    provider: "openai"
    model_alias: "openai_small"
    purpose: "small local code changes"
    max_input_tokens: 32000
    max_output_tokens: 3000
    max_context_chars: 128000
    reasoning_effort: "low"
    verbosity: "low"
    structured_output: true
    allow_tools: false
    allow_direct_patch: true
    budget_pool: "builder"

  general_builder:
    provider: "openai"
    model_alias: "openai_builder"
    purpose: "normal coding tasks and guided repairs"
    max_input_tokens: 64000
    max_output_tokens: 6000
    max_context_chars: 256000
    reasoning_effort: "medium"
    verbosity: "medium"
    structured_output: true
    allow_tools: false
    allow_direct_patch: true
    budget_pool: "builder"

  coding_optimized_builder:
    provider: "openai"
    model_alias: "openai_coding_builder"
    purpose: "coding-optimized patch generation when available"
    max_input_tokens: 64000
    max_output_tokens: 6000
    max_context_chars: 256000
    reasoning_effort: "medium"
    verbosity: "medium"
    structured_output: true
    allow_tools: false
    allow_direct_patch: true
    budget_pool: "builder"

  frontier_reviewer:
    provider: "openai"
    model_alias: "openai_frontier"
    purpose: "architecture, planning, complex diagnosis, final review"
    max_input_tokens: 128000
    max_output_tokens: 4000
    max_context_chars: 512000
    reasoning_effort: "high"
    verbosity: "medium"
    structured_output: true
    allow_tools: false
    allow_direct_patch: false
    budget_pool: "reviewer"

  frontier_coding_reviewer:
    provider: "openai"
    model_alias: "openai_frontier_coding"
    purpose: "high-end coding diagnosis and review when available"
    max_input_tokens: 128000
    max_output_tokens: 6000
    max_context_chars: 512000
    reasoning_effort: "medium"
    verbosity: "medium"
    structured_output: true
    allow_tools: false
    allow_direct_patch: false
    budget_pool: "reviewer"

model_aliases:
  openai_nano: "gpt-5-nano"
  openai_small: "gpt-5-mini"
  openai_builder: "gpt-5-mini"
  openai_coding_builder: "gpt-5.1-codex-mini"  # optional only if available
  openai_frontier: "gpt-5.2"
  openai_frontier_coding: "gpt-5.2-codex"  # optional only if available

pricing:
  currency: "usd"
  source_url: "https://developers.openai.com/api/docs/pricing"
  retrieved_or_verified_date: "2026-05-11"
  roles:
    mechanical_worker:
      input_usd_per_1m_tokens: 0.0
      cached_input_usd_per_1m_tokens: 0.0
      output_usd_per_1m_tokens: 0.0
    simple_builder:
      input_usd_per_1m_tokens: 0.0
      cached_input_usd_per_1m_tokens: 0.0
      output_usd_per_1m_tokens: 0.0
    general_builder:
      input_usd_per_1m_tokens: 0.0
      cached_input_usd_per_1m_tokens: 0.0
      output_usd_per_1m_tokens: 0.0
    coding_optimized_builder:
      input_usd_per_1m_tokens: 0.0
      cached_input_usd_per_1m_tokens: 0.0
      output_usd_per_1m_tokens: 0.0
    frontier_reviewer:
      input_usd_per_1m_tokens: 0.0
      cached_input_usd_per_1m_tokens: 0.0
      output_usd_per_1m_tokens: 0.0
    frontier_coding_reviewer:
      input_usd_per_1m_tokens: 0.0
      cached_input_usd_per_1m_tokens: 0.0
      output_usd_per_1m_tokens: 0.0

budget:
  project_total_budget_usd: 5.0
  max_task_cost_usd: 0.10
  role_budgets_usd:
    worker: 1.0
    builder: 3.0
    reviewer: 1.0
    emergency: 1.0

policies:
  allow_frontier_direct_patch: false
  budget_optimization_enabled: true
  service_tiers:
    default_builder_tier: "flex"
    fallback_builder_tier: "default"
    priority_enabled: false
```

Pricing values should remain config-driven. Do not bake current OpenAI prices into code. If example pricing is added later, cite the source and make clear it is editable.

## 6. Model Role Definitions

Role names are capability-driven and must not imply fixed provider or fixed price:

- `mechanical_worker`
  - tiny deterministic coding tasks
  - docstrings, small tests, regex, JSON/CSV transforms, type hints, boilerplate, small helpers
  - default to the smallest configured OpenAI model
- `simple_builder`
  - small local code changes, helpers, parsers, validators, small scripts, localized fixes
  - default to the smallest configured model with enough context/output for patch work
- `general_builder`
  - normal coding tasks, moderate features, integration across a few files, test generation, debugging, repair after smaller role failure
  - default to a mini-class model
- `frontier_reviewer`
  - architecture, planning, complex debugging, difficult diagnosis, final review, escalation guidance
  - diagnosis/review by default
  - direct patching disabled unless both role config and global policy explicitly allow it

Official docs checked on 2026-05-11:

- Latest model guide identifies `gpt-5.5` as the current flagship model and recommends the Responses API for reasoning/tool/multiturn use cases: <https://developers.openai.com/api/docs/guides/latest-model.md>
- Models page search result says smaller variants include `gpt-5.4-mini` and `gpt-5.4-nano`: <https://developers.openai.com/api/docs/models>
- Data residency docs list dated Responses API model IDs including `gpt-5.5-2026-04-23`, `gpt-5.4-mini-2026-03-17`, and `gpt-5.4-nano-2026-03-17`: <https://developers.openai.com/api/docs/guides/your-data#which-models-and-features-are-eligible-for-data-residency>
- Pricing docs list current per-1M token prices by service tier and include `gpt-5-nano`, `gpt-5-mini`, `gpt-5.2`, and other GPT models: <https://developers.openai.com/api/docs/pricing>
- Priority processing docs confirm Responses API supports request-level `service_tier="priority"` and reports the actual tier used in the response object: <https://developers.openai.com/api/docs/guides/priority-processing>
- GPT-5.2-Codex docs identify `gpt-5.2-codex` as a reasoning model optimized for long-horizon agentic coding tasks and available in the Responses API: <https://developers.openai.com/api/docs/models/gpt-5.2-codex>
- Deprecation docs mention `gpt-5.1-codex-mini` as an older model scheduled for shutdown on 2026-07-23, so it must not be a required default: <https://developers.openai.com/api/docs/deprecations#2026-04-22-legacy-gpt-model-snapshots>

No official OpenAI "micro" model was found in the checked docs. Keep `simple_builder` as a role and map it to a real configured model such as a nano or mini variant.

Current initial default recommendation:

- `mechanical_worker` -> `gpt-5-nano`
- `simple_builder` -> `gpt-5-nano` only for strongly validated tiny tasks; otherwise `gpt-5-mini`
- `general_builder` -> `gpt-5-mini`
- `coding_optimized_builder` -> `gpt-5.1-codex-mini` only if officially available in the account; otherwise `gpt-5-mini`
- `frontier_reviewer` -> `gpt-5.2`
- `frontier_coding_reviewer` -> `gpt-5.2-codex` only if available and budget-approved

### OpenAI Model Research Table

| Model | Default role | Strengths | Weaknesses / avoid | Default reasoning | Default service tier | Recommended Python/Linux terminal use cases |
| --- | --- | --- | --- | --- | --- | --- |
| `gpt-5-nano` | `mechanical_worker`, classifier, summarizer | Very low cost, fast mechanical transformations, simple extraction | Avoid architecture, ambiguous bugs, multi-file reasoning, shell planning, direct large patches, security-sensitive edits | `none` or `low` | `flex` for non-urgent work, `default` fallback | task classification, log summarization, extracting pytest/ruff/mypy errors, regex, JSON/CSV transforms, docstrings, type hints, boilerplate, tiny helpers, very small tests |
| `gpt-5-mini` | `general_builder`, default implementation model | Normal Python implementation, localized multi-file changes, test generation, moderate refactors, repairing nano outputs | Avoid deep architecture, complex debugging, final review of risky changes, large unclear migrations | `low` for straightforward changes, `medium` for debugging/refactor | `flex` for non-urgent builder calls, `default` fallback | normal code patches, CLI utilities, config/schema changes, pytest generation, simple Linux terminal workflow reasoning |
| `gpt-5.1-codex-mini` if available | `coding_optimized_builder` alternative | Coding-optimized patch generation and Codex-like builder workflows | Do not assume availability; deprecation docs list it as scheduled for shutdown on 2026-07-23; avoid making it required | `medium` when used | `default` unless official pricing/tier support says otherwise | optional account-gated coding builder experiments, never a hard dependency |
| `gpt-5.2` | `frontier_reviewer`, planner, difficult diagnosis | Architecture, planning, hard bugs, complex refactors, ambiguous failures, reviewing escalation packets | Diagnosis/review by default; avoid direct patches unless `allow_frontier_direct_patch=true` and budget gate passes | `medium`; `high`/`xhigh` only for hard blockers with explicit budget gate | `default`; `priority` disabled unless explicitly configured | review packets, decomposition strategy, root-cause analysis, risk review |
| `gpt-5.2-codex` if available | `frontier_coding_reviewer` / high-end coding model | Long-horizon agentic coding, difficult Python/Linux workflows, complex multi-file refactors, final review of risky patches | Use sparingly due to cost; diagnosis-first; direct patching disabled by default | `medium`; `high`/`xhigh` only with explicit budget gate | `default`; `priority` disabled unless explicitly configured | complex coding diagnosis, high-risk patch review, rare budget-approved coding escalation |

## 7. Routing Rules

The router should select the smallest role with a reasonable chance of passing validation.

Inputs:

- task type
- declared complexity and risk
- allowed file count
- expected diff size
- context size
- whether the task is mechanical or ambiguous
- whether validation commands exist
- previous attempt failures
- convergence, stagnation, and divergence metrics
- patch contract failures
- role context/output limits
- budget remaining by task, project, and role pool
- whether architecture/review/diagnosis is required

Initial routing:

- trivial, mechanical, single-file, low-risk, strong validation -> `mechanical_worker`
- simple, localized, low/medium-risk, small allowed file set -> `simple_builder`
- medium or hard coding task, multi-file integration, test generation, prior simple failure -> `general_builder`
- critical, high ambiguity, architecture review, repeated stagnation/divergence, severe validator regression -> `frontier_reviewer` diagnosis or human escalation

Nano routing guardrails:

- `gpt-5-nano` is allowed for `mechanical_worker` and some `simple_builder` tasks only when:
  - `allowed_files` is narrow
  - validation commands exist
  - expected patch size is small
  - the task is deterministic or mechanical
  - risk is low
- Escalate quickly from nano if validation fails, patch confidence is low, the patch contract is violated, or the task touches more files than expected.
- `gpt-5-mini` is the default for real code patches.
- Frontier models are for planning, diagnosis, and review by default.

### Routing Decision Matrix

| Condition | Initial role | Model default | Required gates | Escalation trigger |
| --- | --- | --- | --- | --- |
| Classification, log summarization, error extraction | `mechanical_worker` | `gpt-5-nano` | no patch or tiny output, low risk | ambiguous result, low confidence, failed validation |
| Tiny deterministic patch | `mechanical_worker` | `gpt-5-nano` | 1-2 allowed files, validation commands present, small expected diff | any validator failure, patch scope growth, patch contract issue |
| Simple localized code patch | `simple_builder` | `gpt-5-mini`, with `gpt-5-nano` only under nano guardrails | low risk, bounded file list, validation exists | repeated validation failure or non-convergence |
| Normal implementation or tests | `general_builder` | `gpt-5-mini` | budget and context fit role limits | stagnation, divergence, ambiguity, context overflow |
| Coding-optimized builder experiment | `coding_optimized_builder` | `gpt-5.1-codex-mini` if available, else `gpt-5-mini` | explicit config, availability check, pricing configured | provider unavailable, deprecation risk, budget block |
| Architecture, planning, hard diagnosis | `frontier_reviewer` | `gpt-5.2` | diagnosis-only, direct patch disabled, reviewer budget available | guided fix fails or budget/runtime exhausted |
| High-end coding review | `frontier_coding_reviewer` | `gpt-5.2-codex` if available | availability check, explicit config, budget gate, diagnosis-first | direct patch requested while policy disabled, budget block |

Escalation routing:

- `mechanical_worker` or `simple_builder` first when context and risk permit
- `general_builder` for repair after low-tier failure, patch contract failure, or context exceeding lower role limits
- `frontier_reviewer` for diagnosis when deterministic convergence says the builder is stuck or unsafe
- `general_builder` applies reviewer guidance through the same patch contract
- human escalation if guided repair fails, budget/runtime stops, or policy blocks model escalation

Default escalation path:

`mechanical_worker` / nano -> `simple_builder` or `general_builder` / mini -> `frontier_reviewer` diagnosis -> `general_builder` guided fix -> human escalation.

## 8. Escalation Rules

Escalate from a lower builder role when:

- validation fails repeatedly
- attempts stagnate or diverge
- syntax, type, test, or patch-scope failures worsen
- output violates the patch contract
- context exceeds lower role limits
- task ambiguity or risk requires diagnosis
- role budget is exhausted but reviewer budget remains
- runtime policy says to stop or request diagnosis

Do not escalate merely because one retry failed.

`frontier_reviewer` remains diagnosis/review by default:

- may produce root cause, minimal fix strategy, focus files, risks, and next builder instruction
- must not produce direct diffs, shell commands, file writes, or large code blocks
- must respect global `allow_frontier_direct_patch: false`

Schema names should change from cheap-specific wording:

- `continue_cheap_retry` -> `continue_builder_retry`
- `should_retry_with_cheap_builder` -> `should_retry_with_builder`
- `gemini_instruction` -> `builder_instruction`
- `expensive_reviewer` -> `frontier_reviewer`

## 9. Budget And Cost Changes

Current budget behavior is estimated, config-driven, and persisted to SQLite. Preserve this design.

Required changes:

- replace fixed `cheap_builder_budget_usd` and `expensive_reviewer_budget_usd` with `role_budgets_usd`
- keep `project_total_budget_usd`, `max_task_cost_usd`, `stop_threshold_ratio`, `ledger_path`, and `project_id`
- keep estimated pre-call gating before provider calls
- record provider, model role, concrete model, estimated tokens, estimated cost, actual tokens when available, actual cost when available
- use OpenAI Responses `usage.input_tokens`, `usage.output_tokens`, `usage.total_tokens`, and cached/reasoning token details when present
- preserve estimated cost before calls and update ledger with actual usage after calls
- keep pricing config-driven by role/model alias and easy to update
- update reports from tier-centric fields to role-centric fields:
  - calls by role
  - cost by role
  - blocked calls by role
  - largest context/input/output sizes
  - actual-vs-estimated token/cost fields when available

The OpenAI Costs/Usage APIs are operator observability tools, not required in the first provider implementation. The orchestrator should first account per response using response usage metadata.

### Pricing Defaults

Implementation must pull or encode current official OpenAI API pricing defaults into `config.example.yaml` and built-in defaults. Pricing remains config-driven and must not be embedded in routing or business logic.

Required pricing metadata for each configured role/model/tier:

- `source_url`
- `retrieved_or_verified_date`
- `input_per_1m`
- `cached_input_per_1m`
- `output_per_1m`
- `service_tier`
- explicit tier prices or multiplier metadata when available

Official pricing docs checked on 2026-05-11 show prices per 1M tokens. Initial defaults should include at least:

| Model | Service tier | Input / 1M | Cached input / 1M | Output / 1M | Planned default role |
| --- | --- | ---: | ---: | ---: | --- |
| `gpt-5-nano` | standard/default | 0.05 | 0.005 | 0.4 | `mechanical_worker` |
| `gpt-5-nano` | flex | 0.025 | 0.0025 | 0.2 | non-urgent `mechanical_worker` |
| `gpt-5-mini` | standard/default | 0.25 | 0.025 | 2 | `general_builder`, normal `simple_builder` |
| `gpt-5-mini` | flex | 0.125 | 0.0125 | 1 | non-urgent builder work |
| `gpt-5-mini` | priority | 0.45 | 0.045 | 3.6 | disabled by default |
| `gpt-5.2` | standard/default | 1.75 | 0.175 | 14 | `frontier_reviewer` |
| `gpt-5.2` | flex | 0.875 | 0.0875 | 7 | budget-optimized diagnosis if latency permits |
| `gpt-5.2` | priority | 3.5 | 0.35 | 28 | disabled by default |

Pricing for `gpt-5.1-codex-mini` and `gpt-5.2-codex` must be verified from official pricing/model docs at implementation time before enabling those aliases. If no official price is exposed for an optional coding model, the provider config must reject live calls for that alias until pricing is configured explicitly.

Service tier policy:

- Preserve and evolve the existing Flex/Standard policy as OpenAI service-tier policy.
- Treat the OpenAI pricing page's Standard table as service tier `default` in request config unless the API uses another explicit value.
- Support configured service tier values:
  - `default`
  - `flex`
  - `priority`
  - `batch` / offline only when a future batch workflow is explicitly implemented
- Prefer `flex` for non-urgent low-cost builder work when budget optimization is enabled.
- Fall back to `default` when Flex timeout or latency exceeds policy.
- Keep `priority` disabled by default and require explicit config plus a budget gate.
- Record the requested service tier and the actual `response.service_tier` when present.

Reasoning and output budget policy:

- Reasoning tokens are billed as output tokens and consume output/context headroom.
- Responses API usage may expose `output_tokens_details.reasoning_tokens`; record it when present, but do not rely on it for pre-call gating.
- Pre-call estimates must reserve output/reasoning headroom by role. Frontier roles should reserve larger headroom than nano/mini builder roles.

## 10. Validation And Rollback Preservation Plan

Keep these components intact while swapping the model provider:

- `SafePatchApplier`
- `PatchValidator`
- `CommandSafetyValidator`
- `SyntaxValidator`
- `TestValidator`
- `GitManager.checkpoint()`
- `GitManager.rollback_to_checkpoint()`
- `GitManager.commit_task()`
- `LimitGuard`
- `TimeoutGuard`
- escalation package generation

Patch parser changes should be narrow:

- update error text from "OpenCode output" to "builder output"
- extend `ParsedPatch` to include `assumptions` and `risk_notes`
- continue accepting unified diff or structured JSON with `patch`, `touched_files`, `summary`, and `confidence`
- reject shell commands, prose-only output, unsafe paths, excessive patch size, excess changed files, and deletes unless allowed

OpenAI provider must return data to the same safety pipeline. It must not write files directly.

## 11. Documentation Update Plan

Remove or rewrite:

- `docs/OPENCODE_SETUP.md`
- `docs/OPEN_CODE_SETUP.md`
- OpenCode sections in `README.md`
- OpenCode section in `AGENTS.md`
- OpenCode setup and trial text in `docs/USER_GUIDE.md`
- OpenCode/Gemini sections in `docs/REAL_WORLD_TRIAL.md`
- OpenCode provider notation in config examples
- Gemini Flex/Standard cheap-tier docs

Add or rewrite:

- OpenAI setup guide:
  - `OPENAI_API_KEY` only from environment
  - no committed secrets
  - direct Responses API use
- model role guide:
  - capability role definitions
  - role-to-model alias mapping
  - how to update model aliases and pricing
- provider config guide:
  - OpenAI-only now
  - future provider extension points
- cost-aware routing guide:
  - role escalation
  - reviewer diagnosis-only policy
- first real OpenAI trial runbook:
  - one tiny task
  - clean branch
  - strict allowed files
  - low budget
  - fake provider tests first
- migration notes:
  - OpenCode removed intentionally
  - old config keys and docs no longer apply

## 12. Test Plan

Add or refactor tests in small groups:

- config parsing:
  - model role schema
  - model aliases
  - role budgets
  - pricing metadata and per-service-tier pricing
  - service tier policy defaults and fallback settings
  - OpenAI provider settings
  - old OpenCode config rejection or migration behavior
- provider:
  - fake provider returns builder contract
  - OpenAI provider reads API key env var only
  - missing API key fails cleanly
  - structured builder output is parsed
  - refusal/error/incomplete responses fail safely
  - usage metadata is captured
- routing:
  - mechanical task -> `mechanical_worker`
  - simple localized task -> `simple_builder`
  - medium/hard task -> `general_builder`
  - ambiguous/reviewer task -> `frontier_reviewer`
  - lower-role context overflow escalates role
  - budget exhaustion blocks or escalates according to policy
- diagnosis:
  - reviewer remains diagnosis-only
  - direct patch rejected when policy is false
  - reviewer guidance feeds builder retry through `builder_instruction`
- builder path:
  - fake provider emits unified diff
  - fake provider emits structured JSON patch
  - patch validation still rejects outside allowed files
  - validation failure triggers retry
  - rollback still happens on failure
- budget ledger:
  - spend by role pool
  - estimated and actual token fields
  - cached input token accounting when present
  - reasoning token details recorded when present
  - requested vs actual service tier recorded when present
  - report uses role-centric fields
- docs/config regression:
  - `rg -n "OpenCode|opencode|Gemini|gemini|cheap_builder|expensive_reviewer|Flex|Standard"` should return only migration notes, if any

Full validation after each phase:

```bash
.venv/bin/ruff check .
.venv/bin/mypy .
.venv/bin/pytest
```

## 13. Step-By-Step Implementation Phases

Phase 1: role schema, config migration, and provider scaffolding

- Add provider/model role config models.
- Add role-budget config.
- Add role resolution from capability role to provider/model/service tier.
- Add provider request/response contracts.
- Add fake provider scaffolding for deterministic tests.
- Add OpenAI provider guardrail skeleton with env-only API key handling.
- Keep current behavior passing through compatibility where needed.
- Add config parsing, role resolution, pricing/service-tier, and fake provider tests.
- Do not call OpenAI yet.

Phase 2: OpenAI provider implementation

- Add the OpenAI Python SDK dependency deliberately.
- Implement `coding_orchestrator/models/openai_provider.py` using the Responses API.
- Add structured output request/response mapping.
- Capture provider-reported usage fields for token/cost accounting.
- Add OpenAI provider tests that mock the SDK and never call the network.

Phase 3: role-based routing

- Replace model-string routing with model-role routing.
- Remove cheap/expensive assumptions from classifier/router logic.
- Rename convergence actions and diagnosis result fields with compatibility shims if needed.
- Add routing and escalation tests.

Phase 4: OpenAI builder path

- Replace `OpenCodeRunner` usage in the engine with provider calls.
- Use Responses API and structured outputs for builder responses when configured.
- Keep unified diff fallback if structured parsing is disabled.
- Preserve patch validation and rollback.
- Add fake model output tests for both diff and JSON patch modes.

Phase 5: OpenCode removal and docs migration

- Delete `coding_orchestrator/tools/opencode_runner.py`.
- Remove `OpenCodeSettings`.
- Remove `opencode` config sections.
- Remove OpenCode docs or convert only one migration note.
- Update README, AGENTS.md, User Guide, Configuration, Roadmap, and Real-World Trial docs.
- Remove provider strings using OpenCode provider notation.
- Rename tests away from OpenCode naming.

Phase 6: validation and summary report

- Run ruff, mypy, and pytest.
- Fix failures in small patches.
- Run final `rg` checks for stale terms.
- Produce a concise migration report.

## 14. Risks, Unknowns, And Blockers

No documentation blocker was hit. OpenAI docs were reachable through the MCP server.

Risks:

- The current engine couples builder execution, tier fallback, budget estimate, and OpenCode settings in one method. Refactoring this in one patch would be risky.
- SQLite budget reports currently expose cheap/expensive and Flex/Standard fields. Changing reports may affect tests and user expectations.
- Renaming schema fields may break existing `logs/state.json`; a compatibility strategy is needed if old state files matter.
- Official pricing changes over time. Pricing must stay config-driven and should not be hardcoded.
- The OpenAI Python SDK dependency is not currently in `pyproject.toml`; Phase 2 must add it deliberately with tests.
- Structured Outputs improve contract reliability but do not replace patch validation, tests, or rollback.
- Hosted OpenAI tools and function calling should remain disabled by default to preserve the rule that Python owns deterministic tool execution.
- `gpt-5.1-codex-mini` appears in official deprecation docs as scheduled for shutdown on 2026-07-23. It should be optional and account-gated, not a required migration target.
- `gpt-5.2-codex` is officially described as optimized for long-horizon agentic coding, but pricing and account availability must be verified before live use.
- Service tier names differ between pricing tables and request fields: the pricing page uses Standard, while Responses request config uses `service_tier` values such as `priority` and response objects may report `default`. The implementation must normalize this explicitly.

Unknowns:

- Whether old persisted state files must remain readable after field renames.
- Whether migration notes may keep the words OpenCode/Gemini after the cleanup, or whether final `rg` should be completely clean except this plan.
- Whether `gpt-5.2-codex` pricing should be inferred from a related coding model only if official docs do not expose it, or whether live calls should be blocked until exact pricing is configured.
- Whether to use moving model aliases such as `gpt-5-mini` / `gpt-5.2`, pinned dated snapshots, or both with config comments.

## 15. Resolved User Decisions

The user clarified these decisions before Phase 1 implementation:

- Strict backward compatibility for old logs, state files, and budget databases is not required. Prefer clean new schema versions and add schema versioning going forward.
- Remove OpenCode completely from runtime, code, configs, docs, comments, examples, naming, setup guides, migration paths, README, AGENTS.md, tests, CLI help text, and architecture docs. Do not keep operational references or compatibility layers.
- Do not leave pricing/config empty. The refactored system should have sensible defaults immediately after install, with official OpenAI pricing values where verified.
- Pricing must remain config-driven and must include source/version metadata. If exact pricing cannot be verified, stop and ask rather than inventing prices.
- Keep nano-class routing. `mechanical_worker` defaults to nano-class models. `simple_builder` may use nano first only when validation confidence is strong; otherwise use mini-class models. `general_builder` defaults to mini-class models. `frontier_reviewer` is diagnosis/review first.
- Preserve and evolve Flex/Standard tier-policy concepts into OpenAI service-tier routing, budgeting, retries, and escalation.

## 16. Phase 1 Scope And Coupling Notes

Phase 1 should be additive and stability-preserving:

- add new schema version fields
- add model role schemas
- add OpenAI provider settings schema
- add model alias defaults
- add pricing metadata and OpenAI pricing defaults
- add service-tier policy config
- add provider request/response contracts and fake provider scaffolding
- add role-resolution helpers from capability role to model alias/service tier
- add tests for new config parsing/defaults, role resolution, pricing/service-tier loading, and fake provider behavior
- preserve existing runtime behavior until later phases

Coupling points to migrate later:

- `WorkflowEngine._run_tiered_builder()` still couples builder execution, tier fallback, budget estimates, and the current runner.
- `BudgetUsage` and `BudgetLedger` still expose cheap/expensive and tier-centric report fields.
- `CheapBuilderTierPolicy` still uses Flex/Standard names from the existing runtime path.
- diagnosis schemas still contain cheap/Gemini-specific names.
- docs, README, AGENTS.md, config examples, and tests still contain OpenCode/Gemini terminology until the removal phase.
- `OpenAIProvider.generate()` now exists for Phase 2 but remains disabled unless explicitly enabled in config (`providers.openai.runtime_enabled=true`).
- `pyproject.toml` now includes the OpenAI Python SDK after Phase 2 provider-path integration.

Contradictions before Phase 1:

- None blocking Phase 1. Complete OpenCode removal is intentionally deferred because the user requested Phase 1 only and existing behavior must remain stable during schema introduction.

## 17. Phase 2 Implementation Notes (2026-05-11)

Implemented in Phase 2:

- Added a provider-backed builder path in `WorkflowEngine` behind `policies.builder_execution_backend`.
- Kept `legacy_opencode` as the default backend for runtime stability.
- Added `role_provider` and `auto` backends with optional fallback to legacy OpenCode (`policies.provider_fallback_to_opencode`).
- Integrated role resolution with `resolve_model_role()` for provider calls.
- Added builder role selection heuristics:
  - tiny, strongly bounded validated tasks -> `mechanical_worker`
  - simple local tasks -> `simple_builder`
  - retries, higher risk, or larger scope -> `general_builder`
- Preserved frontier diagnosis-only behavior by never routing builder patch generation to `frontier_*` roles.
- Preserved existing safety flow: limits and budget pre-checks, patch parse, patch validation, `git apply --check`, validators, rollback, and escalation.
- Added service-tier normalization from legacy tier policy (`standard` -> `default`) for provider pricing and ledger records.
- Added provider request/response metadata and usage capture under `state.tool_results`.
- Added OpenAI provider runtime implementation guardrails:
  - disabled unless `providers.openai.runtime_enabled=true`
  - API key from environment only
  - optional SDK import with clear configuration error if missing
  - Responses API call shape with reasoning and verbosity controls
- Added `openai>=2.0` to dependencies.
- Added engine/provider integration tests:
  - role selection for tiny tasks
  - structured provider patch output through existing patch safety
  - failed validation rollback with provider path
  - budget ledger records role/model/provider/service tier
  - legacy OpenCode path remains unchanged by default

Remaining for Phase 3:

- Remove OpenCode runtime path and related config/docs/tests completely.
- Move all remaining cheap/expensive naming and Flex/Standard-only reporting fields to role-centric naming.
- Replace legacy `ModelRouter` string assumptions with role-first routing everywhere.

## 18. Phase 2.5 Model Catalog Refresh (2026-05-11)

Completed scope:

- Updated OpenAI alias catalog to current defaults:
  - `gpt-5.4-nano` for `openai_nano`
  - `gpt-5.4-mini` for `openai_mini`
  - `gpt-5.3-codex` for coding-specialized roles
  - `gpt-5.5` for frontier review
  - `gpt-5.5-pro` for manual approval emergency review
- Added role entries for `ultra_cheap_classifier`, `frontier_balanced_reviewer`,
  `emergency_pro_reviewer`, `legacy_reasoning_fallback`, and
  `non_reasoning_instruction_follower`.
- Added explicit policy gates:
  - `allow_xhigh_reasoning: false`
  - `allow_emergency_pro_reviewer: false`
- Updated pricing defaults with verified OpenAI entries and service tiers, including:
  - `default`, `flex`, `priority`, and `batch` where documented
  - long-context pricing fields for models where docs specify long-context multipliers
  - explicit `null` cached-input discounts for pro models
- Kept OpenCode runtime path and engine safety controls unchanged.

References used:

- `https://developers.openai.com/api/docs/pricing`
- `https://developers.openai.com/api/docs/guides/flex-processing`
- `https://developers.openai.com/api/docs/guides/priority-processing`
- model pages for `gpt-5.3-codex`, `gpt-5.5`, `gpt-5.5-pro`, `gpt-5.4`,
  `gpt-5.4-pro`, `gpt-5.4-mini`, `gpt-5.4-nano`, `gpt-5-mini`, `gpt-5-nano`,
  `gpt-5`, and `gpt-4.1`.
