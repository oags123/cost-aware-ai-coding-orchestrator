# Review Packet Specification

Status: planning only.

## Purpose

Review packets are compact, structured inputs for expensive diagnosis/review. They should be built by the cheap model or deterministic summarizers before any expensive model call.

The expensive model should never receive raw repo dumps.

## Packet Contents

```yaml
task:
  id: T-042
  title: Fix parser edge case
  complexity: medium
  risk: low

budget:
  remaining_task_usd: 0.04
  projected_review_usd: 0.03

attempts:
  count: 2
  convergence_summary: improving tests but syntax regression on retry 2

diff:
  changed_files:
    - src/parser.py
  summary: updates branch handling
  compact_patch: |
    ...

validation:
  current_failures:
    - pytest tests/test_parser.py::test_empty_branch
  compact_stdout: |
    ...
  compact_stderr: |
    ...

question:
  type: diagnosis
  prompt: What is the most likely root cause and next cheap-builder instruction?
```

## Size Limits

Proposed defaults:

- max packet chars: 24000
- max diff chars: 10000
- max stdout chars: 4000
- max stderr chars: 4000
- max file snippets: 5
- max snippet chars each: 2000

## Expensive Model Output Contract

Diagnosis-only response:

```yaml
root_cause: ...
risk_assessment: ...
recommended_next_instruction: ...
files_to_focus:
  - path.py
avoid:
  - broad refactor
confidence: 0.0
```

No patch should be accepted from expensive model output unless direct patch mode is explicitly approved.

