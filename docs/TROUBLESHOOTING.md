# Troubleshooting

## `python: command not found`

Use `python3` or the venv Python:

```bash
.venv/bin/python -m coding_orchestrator.app validate
```

## OpenCode Missing

If real mode is enabled and OpenCode is missing, install it and confirm:

```bash
command -v opencode
opencode --version
```

Then authenticate and list models:

```bash
opencode auth login
opencode models --refresh
opencode models
```

See [OpenCode Setup](OPENCODE_SETUP.md). The orchestrator does not silently
fall back to dry-run when real mode is enabled.

## OpenCode Returns Prose Instead Of A Patch

The current patch contract accepts only a unified diff or JSON containing
`patch`, `touched_files`, `summary`, and `confidence`. Free-form instructions
are rejected.

Use a smaller task, narrower `allowed_files`, and `output_mode: "unified_diff"`.
Inspect `logs/orchestrator.jsonl` and `logs/state.json` for parser/validator
messages.

## Gemini Key Is Not Visible To OpenCode

This repository does not call Gemini directly. If using Gemini through
OpenCode, export the key and allow the orchestrator to forward it:

```bash
export GEMINI_API_KEY="..."
```

```yaml
opencode:
  allowed_env_vars:
    - "GEMINI_API_KEY"
```

Also confirm OpenCode sees the provider:

```bash
opencode auth list
opencode models --refresh
opencode models
```

## Docker Socket Permission Denied

If Docker reports permission denied for `/var/run/docker.sock`, the current user cannot access Docker. Fix local Docker permissions before running compose commands.

## Real OpenCode Mode In Docker

The current project Dockerfile installs this Python package and Git. It does not
install OpenCode or configure provider credentials. Use local venv execution for
the first real task unless you explicitly extend the container setup.

## Telegram Alerts Do Not Send

Telegram alerts are disabled by default. Enable them in `config.yaml`:

```yaml
telegram:
  enabled: true
```

Then export the configured environment variables before starting the
orchestrator:

```bash
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
```

Do not store those values in repo files. If Telegram is enabled but env vars are
missing, `missing_env_policy: "warn"` skips the alert and logs a warning.
`missing_env_policy: "fail"` stops with a clear configuration error.

## Git Commit Identity Missing

Configure identity locally:

```bash
git config user.email "you@example.com"
git config user.name "Your Name"
```

or globally:

```bash
git config --global user.email "you@example.com"
git config --global user.name "Your Name"
```

## Push To Local Bare Repository Fails

For a local bare remote, check ownership and permissions on the bare repo path. If Git reports dubious ownership and you trust the path:

```bash
git config --global --add safe.directory /path/to/bare.git
```

## Validation Fails

Run each command directly:

```bash
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/mypy .
```

Inspect `logs/orchestrator.jsonl`, `logs/state.json`, and `logs/escalations/` for task-level context.

## First Real Trial Fails

Use [Real-World Trial Runbook](REAL_WORLD_TRIAL.md). Keep the first task tiny,
use `git.require_clean_worktree: true`, and inspect:

```bash
git status --short
git diff --stat
.venv/bin/python -m coding_orchestrator.app report
```
