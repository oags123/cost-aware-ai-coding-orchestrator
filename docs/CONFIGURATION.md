# Configuration

Config is YAML and loaded from `config.yaml` by default. If no config file exists, built-in defaults are used. `config.example.yaml` is the starting point.

## Main Sections

- `repo_path` - repository root for task execution.
- `state_path` - JSON state file path.
- `log_path` - JSONL event log path.
- `model_routing` - complexity to model-tier mapping.
- `timeouts` - task, attempt, and total runtime settings.
- `retries` - global retry defaults.
- `budget` - estimated task/project cost limits.
- `limits` - hard token, context, patch, stdout/stderr, and validation output caps.
- `inference` - cheap builder Flex/Standard tier policy.
- `convergence` - cheap retry convergence/divergence thresholds.
- `diagnosis` - diagnosis-only reviewer packet and dry-run interface settings.
- `telegram` - optional blocker/stop alert notifications.
- `pricing` - model-role pricing and output token assumptions.
- `validation` - max changed files, forbidden paths, default commands.
- `tool_permissions` - allowlisted deterministic command names.
- `opencode` - dry-run and real OpenCode execution settings.
- `git` - dirty-worktree and rollback preservation settings.

## OpenAI Model Catalog (Phase 2.5)

Model aliases are capability-driven and model IDs are current OpenAI defaults:

```yaml
model_aliases:
  openai_ultra_cheap_legacy: "gpt-5-nano"
  openai_nano: "gpt-5.4-nano"
  openai_mini_legacy: "gpt-5-mini"
  openai_mini: "gpt-5.4-mini"
  openai_codex: "gpt-5.3-codex"
  openai_frontier_balanced: "gpt-5.4"
  openai_frontier: "gpt-5.5"
  openai_frontier_pro: "gpt-5.5-pro"
  openai_legacy_reasoning: "gpt-5"
  openai_non_reasoning: "gpt-4.1"
```

Reasoning is request-level policy (`reasoning_effort`), not part of the model ID.
`gpt-5.3-codex` with `medium` and `high` reasoning uses the same model string.

## Role Defaults (Phase 2.5)

- `mechanical_worker` defaults to `gpt-5.4-nano` (`flex`, low/none reasoning).
- `simple_builder` and `general_builder` default to `gpt-5.4-mini`.
- `coding_optimized_builder` and `frontier_coding_reviewer` default to `gpt-5.3-codex`.
- `frontier_reviewer` defaults to `gpt-5.5`.
- `emergency_pro_reviewer` maps to `gpt-5.5-pro` and requires manual approval.

Policy guardrails:

```yaml
policies:
  allow_frontier_direct_patch: false
  allow_xhigh_reasoning: false
  allow_emergency_pro_reviewer: false
```

## OpenCode Settings

OpenCode is installed and authenticated separately from this package. See
[OpenCode Setup](OPENCODE_SETUP.md).

```yaml
opencode:
  enabled: false
  dry_run: true
  executable: "opencode"
  default_model: "opencode-local"
  max_runtime_seconds: 300
  output_mode: "unified_diff"
  allowed_env_vars: []
  extra_args: []
```

Real mode requires both `enabled: true` and `dry_run: false`.

Only environment variables listed in `allowed_env_vars` are forwarded to OpenCode, in addition to basic process environment like `PATH` and `HOME`.

For Gemini through OpenCode:

```yaml
opencode:
  allowed_env_vars:
    - "GEMINI_API_KEY"
```

The `default_model` value must be the exact `provider/model` string reported by
`opencode models`. The built-in pricing defaults are planning estimates and do
not prove that the model is available in your OpenCode installation.

## Budget, Pricing, and Limits

Budget checks use configured pricing and persist estimates to SQLite:

```yaml
budget:
  ledger_path: "logs/budget.sqlite"
  project_id: "default"
  project_total_budget_usd: 5.0
  cheap_builder_budget_usd: 3.0
  expensive_reviewer_budget_usd: 1.0
  emergency_budget_usd: 1.0

pricing:
  roles:
    cheap_builder:flex:
      provider: "google-gemini"
      model: "gemini-3.1-flash-lite"
      inference_tier: "flex"
      input_usd_per_1m_tokens: 0.125
      output_usd_per_1m_tokens: 0.75
      max_output_tokens: 4000
      budget_pool: "cheap_builder"
    cheap_builder:standard:
      provider: "google-gemini"
      model: "gemini-3.1-flash-lite"
      inference_tier: "standard"
      input_usd_per_1m_tokens: 0.25
      output_usd_per_1m_tokens: 1.50
      max_output_tokens: 4000
      budget_pool: "cheap_builder"
```

Pricing values in `config.example.yaml` are planning placeholders. Audit and
update them before real paid use.

Hard limits are checked before or immediately after model/OpenCode calls:

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

`context_over_limit_policy` supports `reject` or `trim`. `output_over_limit_policy`
supports `reject` or `truncate`. Validation output can be rejected as a failed
validation result or truncated for state/log safety.

## Inference Tier Settings

The cheap builder path defaults to Gemini Flex and only uses Standard as a
bounded fallback after Flex timeout policy triggers:

```yaml
inference:
  cheap_builder:
    default_tier: "flex"
    fallback_tier: "standard"
    flex:
      max_attempt_runtime_seconds: 600
      max_consecutive_timeouts: 2
      timeout_rate_threshold: 0.5
    max_standard_fallbacks_per_run: 1
    max_standard_fallback_cost_usd_per_run: 0.25
```

Flex pricing/model entries are separate from Standard entries. Keep both
config-driven and audit them against current Google pricing before real use.
The builder tier policy does not add a GPT fallback.

Flex/Standard are represented in this project as policy and pricing entries for
the OpenCode builder path. This repository does not call the Gemini API
directly.

## Diagnosis Settings

Diagnosis is disabled by default. When enabled in dry-run mode, it builds a
compact review packet and records a structured placeholder diagnosis. Real
reviewer API calls are not implemented yet.

```yaml
diagnosis:
  enabled: false
  dry_run: true
  provider: "placeholder"
  model: "frontier-reviewer-placeholder"
  model_role: "expensive_reviewer"
  max_input_tokens: 8000
  max_output_tokens: 1500
  max_context_chars: 24000
  max_cost_per_call_usd: 0.25
  max_calls_per_task: 1
  max_calls_per_run: 2
  role_budget_pool: "expensive_reviewer"
  diagnosis_only: true
  max_packet_chars: 24000
  max_diff_chars: 10000
  max_stdout_chars: 4000
  max_stderr_chars: 4000
  allow_direct_patch: false
```

`allow_direct_patch` must stay `false` unless a future implementation adds
explicit human approval, budget override, and patch validation for expensive
model output.

## Telegram Alerts

Telegram is disabled by default and is only used for blocker/stop notifications.
It does not approve work, continue runs, change model permissions, or execute
commands.

```yaml
telegram:
  enabled: false
  bot_token_env_var: "TELEGRAM_BOT_TOKEN"
  chat_id_env_var: "TELEGRAM_CHAT_ID"
  missing_env_policy: "warn"
  notify_on_blocked: true
  notify_on_budget_exhausted: true
  notify_on_runtime_exhausted: true
  notify_on_no_runnable_tasks: true
  notify_on_system_error: true
```

The bot token and chat id are read from environment variables only. Do not put
secrets in `config.yaml`, task files, logs, or docs. With
`missing_env_policy: "warn"`, missing environment variables produce a warning
event and skip the alert. With `"fail"`, the notifier raises a clear
configuration error.

## Git Settings

```yaml
git:
  require_clean_worktree: false
  preserve_untracked_dirs:
    - "logs"
    - ".cache"
    - ".pytest_cache"
    - ".mypy_cache"
    - ".ruff_cache"
  preserve_untracked_files:
    - ".gitignore"
```

Set `require_clean_worktree: true` if tasks should refuse to start when tracked files are dirty.
