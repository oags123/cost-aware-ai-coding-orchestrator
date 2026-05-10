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

