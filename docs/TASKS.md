# Tasks

Tasks are small YAML/frontmatter files. The system is designed for many small task files rather than one broad request.

## Example

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
allow_deletes: false
validation_commands:
  - pytest tests/test_user_service.py
---
Implement the user service behavior described here.
```

## Important Fields

- `id` - stable task identifier.
- `title` - short task title.
- `complexity` - `trivial`, `simple`, `medium`, `hard`, or `critical`.
- `risk` - `low`, `medium`, or `high`.
- `depends_on` - task IDs that must complete first.
- `allowed_files` - file boundary for patches and commits.
- `max_attempts` - bounded retry count.
- `max_runtime_seconds` - task runtime cap.
- `max_cost_usd` - estimated task budget.
- `escalation_allowed` - whether to write escalation packages.
- `allow_deletes` - whether patch deletes are allowed.
- `validation_commands` - per-task commands run after builder output.

## Queue Execution

`run-all` loads task files from a directory, orders them by dependencies, skips blocked tasks, and executes one task at a time.

## Retry And Convergence

Each failed attempt records deterministic metrics:

- failing validation commands
- validator error count
- changed file count
- patch size
- builder stdout/stderr size
- failure categories such as syntax, mypy, ruff, pytest, and patch
- repeated vs new failure signatures

The task continues cheap retries only while attempts are converging or remain
inside configured stagnation/divergence thresholds. If the task becomes
non-converging, the engine rolls back and writes a `diagnosis_needed` escalation
package for future diagnosis-only review. No reviewer model is called yet.
