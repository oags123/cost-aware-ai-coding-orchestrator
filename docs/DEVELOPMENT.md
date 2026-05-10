# Development

## Local Environment

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

## Required Checks

```bash
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/mypy .
```

## Coding Conventions

- Use plain Python.
- Keep state typed with Pydantic.
- Keep config in YAML.
- Use subprocess wrappers with timeouts for external commands.
- Keep retries, runtime, and cost bounded.
- Prefer deterministic validators over model judgment.
- Add tests for safety boundaries and failure paths.
- Do not hardcode secrets.

## Useful Smoke Tests

```bash
.venv/bin/python -m coding_orchestrator.app report
.venv/bin/python -m coding_orchestrator.app validate
.venv/bin/python -m coding_orchestrator.app run --task tasks/example_task.md
```

Run task smoke tests in a clean git worktree or temporary clone if you do not want task commits in your current checkout.

## Git Workflow

Before committing:

```bash
git status
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/mypy .
```

Do not commit `.venv`, caches, generated JSON logs, or escalation output.

