# Quickstart

## Install

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

## Validate

```bash
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/mypy .
```

## Run Dry-Run Smoke Tests

Dry-run mode is the default. It does not call OpenCode or apply model output.

```bash
.venv/bin/python -m coding_orchestrator.app report
.venv/bin/python -m coding_orchestrator.app validate
.venv/bin/python -m coding_orchestrator.app run --task tasks/example_task.md
.venv/bin/python -m coding_orchestrator.app run-all --tasks-dir tasks/
```

Run task smoke tests in a clean git worktree or throwaway clone. Successful task execution may create task commits when real changes exist.

## First Real OpenCode Trial

1. Install and authenticate OpenCode outside this project.
2. Copy `config.example.yaml` to `config.yaml`.
3. Set:

```yaml
opencode:
  enabled: true
  dry_run: false
  executable: "opencode"
  default_model: "provider/model"
```

4. Create one small task with a narrow `allowed_files` list.
5. Run:

```bash
.venv/bin/python -m coding_orchestrator.app run --task tasks/your_task.md
```

