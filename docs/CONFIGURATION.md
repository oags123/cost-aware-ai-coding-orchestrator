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
- `pricing` - model-role pricing and output token assumptions.
- `validation` - max changed files, forbidden paths, default commands.
- `tool_permissions` - allowlisted deterministic command names.
- `opencode` - dry-run and real OpenCode execution settings.
- `git` - dirty-worktree and rollback preservation settings.

## OpenCode Settings

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
    cheap_builder:
      provider: "opencode"
      model: "opencode-local"
      input_usd_per_1m_tokens: 0.10
      output_usd_per_1m_tokens: 0.40
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
