# Model Roles Specification

Status: planning only.

## Cheap Model

Responsibilities:

- small patches
- bounded implementation
- retries
- boilerplate
- simple tests
- wiring
- formatting
- local fixes
- validator output compression
- structured summarization
- reranking/filtering/distillation
- compact review packet construction

Must not:

- own architecture
- perform large reasoning loops
- perform open-ended debugging
- redesign systems
- review entire repositories
- receive full raw logs by default

## Expensive Model

Responsibilities:

- root cause diagnosis
- repair strategy
- architecture review
- risk analysis
- edge-case analysis
- suspicious diff review
- retry guidance
- high-risk validation

Must not:

- become primary builder
- rewrite modules by default
- receive full repo context
- receive massive raw logs
- generate huge outputs by default
- produce patches unless explicitly approved by a human and budget gate

## Proposed Config

```yaml
model_roles:
  cheap_builder:
    provider: opencode
    model: provider/small-coding-model
    max_input_tokens: 12000
    max_output_tokens: 4000
  cheap_distiller:
    provider: opencode
    model: provider/small-reasoning-model
    max_input_tokens: 16000
    max_output_tokens: 2000
  expensive_reviewer:
    enabled: false
    diagnosis_only: true
    allow_direct_patch: false
    max_calls_per_task: 1
    max_input_tokens: 8000
    max_output_tokens: 1500
```

## Test Expectations

- Cheap builder is selected for normal repair attempts.
- Expensive reviewer is never selected for patch generation by default.
- Expensive call is blocked if projected cost exceeds remaining budget.
- Expensive output is treated as guidance, not automatically applied code.

