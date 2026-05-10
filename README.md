# Cost-Aware AI Coding Orchestrator

Phase 1 MVP of a controlled local workflow engine for small coding tasks. This is not a free-roaming agent: Python owns the workflow, deterministic tools execute commands, validators decide whether results are acceptable, and model integrations are bounded placeholders.

## Workflow

`request -> classify -> route -> build context -> execute bounded step -> validate -> retry/repair/escalate -> log result`

Implemented pieces:

- Pydantic task and orchestrator state
- YAML config and YAML/frontmatter task files
- Dependency ordering for many small task files
- Model routing placeholders for deterministic, local builder, reviewer, and human approval tiers
- Bounded OpenCode runner interface placeholder
- Retry, timeout, budget, permission, patch, syntax, command, and test validation
- Git diff/status/commit/rollback wrappers
- JSON state and JSONL logs
- Escalation package generation
- CLI entrypoint
- Dockerfile and docker-compose support

## Install

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

## CLI

```bash
.venv/bin/python -m coding_orchestrator.app run --task tasks/example_task.md
.venv/bin/python -m coding_orchestrator.app run-all --tasks-dir tasks/
.venv/bin/python -m coding_orchestrator.app validate
.venv/bin/python -m coding_orchestrator.app report
```

The default config path is `config.yaml`. If it is missing, built-in defaults are used. Start from `config.example.yaml` for local settings.

## OpenCode Modes

The default mode is safe dry-run mode:

```yaml
opencode:
  enabled: false
  dry_run: true
```

Dry-run mode exercises the orchestrator, validators, logging, retry, and escalation flow without calling OpenCode or applying model output.

Real OpenCode mode is config-gated:

```yaml
opencode:
  enabled: true
  dry_run: false
  executable: "opencode"
  default_model: "provider/model"
  output_mode: "unified_diff"
  allowed_env_vars:
    - "ANTHROPIC_API_KEY"
    - "OPENAI_API_KEY"
```

Install and authenticate OpenCode separately before enabling real mode. See the official CLI docs: <https://opencode.ai/docs/cli/>. The orchestrator invokes only `opencode run ...` with a bounded timeout and requires OpenCode output to be either a unified diff or structured JSON with `patch`, `touched_files`, `summary`, and `confidence`.

Patch safety rules:

- `git apply --check` runs before applying.
- Touched files must be inside task `allowed_files` when that list is set.
- Forbidden paths such as `.env`, secrets, credentials, tokens, `/etc/`, and `~/.ssh` are rejected.
- File deletes are rejected unless the task sets `allow_deletes: true`.
- Max changed files is enforced by config.
- Validators run after patch application.

## Docker

```bash
docker compose up
docker compose run orchestrator python -m coding_orchestrator.app run-all --tasks-dir tasks/
```

The container runs as a non-root user and mounts the project plus persistent `logs/`. Docker validation requires the current user to have access to the Docker socket. If `docker compose build` reports permission denied for `/var/run/docker.sock`, fix local Docker permissions before testing the container.

## Validation

```bash
.venv/bin/ruff check .
.venv/bin/mypy .
.venv/bin/pytest
```

## Task Format

```yaml
---
id: T-042
title: Implement user service
complexity: medium
risk: low
depends_on:
  - T-010
allowed_files:
  - src/users/service.py
  - tests/test_user_service.py
max_attempts: 2
max_runtime_seconds: 480
max_cost_usd: 0.06
escalation_allowed: true
validation_commands:
  - pytest tests/test_user_service.py
---
Task details go here.
```

## Phase 1 Boundaries

No LangChain, LangGraph, CrewAI, AutoGen, web UI, Kubernetes, paid APIs, embeddings, semantic memory, vector database, or cloud deployment are included. LLMs do not run shell commands or decide policy.

Codex repository instructions live in `AGENTS.md`; the official Codex CLI docs describe generating this file with `/init`: <https://developers.openai.com/codex/cli/slash-commands#generate-agentsmd-with-init>.
