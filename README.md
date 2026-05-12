# Cost-Aware AI Coding Orchestrator

Local Python orchestrator for bounded coding workflows with strict safety gates.

## What It Does

- Classifies tasks and routes them to capability roles.
- Calls model providers through a typed provider interface.
- Accepts only unified diff or structured JSON patch output.
- Applies patches only after boundary and `git apply --check` validation.
- Runs deterministic validators (`ruff`, `mypy`, `pytest`) after patch apply.
- Rolls back to git checkpoint on failure.
- Enforces bounded retries, runtime, context, output, and cost.
- Persists state/logs and budget ledger locally.

## Runtime Architecture

- Backend: `role_provider` (primary and only runtime backend).
- Provider support today: OpenAI (opt-in), fake provider for tests/dry runs.
- No model-generated shell execution.
- Shell commands run only via deterministic subprocess wrappers with allowlists/timeouts.

## Quick Start

1. Create a virtual environment and install dependencies.
2. Copy `config.example.yaml` to `config.yaml`.
3. For fake-provider local runs, keep OpenAI runtime disabled.
4. For real OpenAI calls, set `OPENAI_API_KEY` and enable `providers.openai.runtime_enabled`.
5. Run:
   - `python -m coding_orchestrator.app run --task tasks/example_task.md`
   - `python -m coding_orchestrator.app report`

## Role Defaults

- `mechanical_worker` -> `gpt-5.4-nano` (`flex`, reasoning `none/low`)
- `classification_worker` -> `gpt-5-nano` (`flex/default`, reasoning `none`, no patch)
- `simple_builder` -> `gpt-5.4-mini` (`flex`, reasoning `low`)
- `general_builder` -> `gpt-5.4-mini` (`flex/default`, reasoning `low/medium`)
- `coding_optimized_builder` -> `gpt-5.3-codex` (`default`, reasoning `medium`)
- `frontier_reviewer` -> `gpt-5.5` (`default`, diagnosis-first)
- `emergency_pro_reviewer` -> `gpt-5.5-pro` (manual approval only)

`mechanical_worker` remains the active routed nano role for tiny deterministic coding and bounded patches. `classification_worker` is a canonical role for classification and summarization workloads, but is currently manual/reserved unless selected explicitly by config or policy.

Legacy names remain accepted for backward compatibility only:

- `ultra_cheap_classifier` -> `classification_worker`
- `openai_ultra_cheap_legacy` -> `openai_classifier_nano`

## Validation Commands

- `.venv/bin/ruff check .`
- `.venv/bin/mypy .`
- `.venv/bin/pytest`

## Docs

- [Architecture](docs/ARCHITECTURE.md)
- [Configuration](docs/CONFIGURATION.md)
- [Model Roles](docs/MODEL_ROLES.md)
- [Cost Control](docs/COST_CONTROL.md)
- [Safety](docs/SAFETY.md)
