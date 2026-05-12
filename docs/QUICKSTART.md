# Quickstart

1. Set up Python environment and dependencies.
2. Copy `config.example.yaml` to `config.yaml`.
3. For test/dry runs, keep `providers.openai.runtime_enabled: false`.
4. For real OpenAI calls, export `OPENAI_API_KEY` and set `runtime_enabled: true`.
5. Run:

```bash
python -m coding_orchestrator.app run --task tasks/example_task.md
python -m coding_orchestrator.app report
```

Validation:

```bash
.venv/bin/ruff check .
.venv/bin/mypy .
.venv/bin/pytest
```
