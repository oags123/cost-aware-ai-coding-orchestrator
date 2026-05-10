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

## Docker Socket Permission Denied

If Docker reports permission denied for `/var/run/docker.sock`, the current user cannot access Docker. Fix local Docker permissions before running compose commands.

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

