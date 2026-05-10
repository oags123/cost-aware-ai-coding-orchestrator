# Convergence And Divergence Logic

Status: implemented for deterministic attempt metrics and cheap-retry decisions.

## Goal

Do not escalate merely because a retry failed. Escalate when cheap retries stop improving or become unsafe.

## Convergence Signals

- fewer failing tests
- fewer validator errors
- same failing area with smaller diff
- smaller or stable patch scope
- fewer touched files
- syntax errors resolved
- test output moves closer to expected behavior
- retry prompt is using previous feedback

## Divergence Signals

- repeated identical failures
- increasing failing tests
- more validator errors
- patch thrashing in same file
- unrelated file changes
- expanding diffs
- syntax regressions
- command safety failures
- forbidden path attempts
- unstable or non-deterministic validation output

## Implemented Attempt Metrics

Track per attempt:

```yaml
attempt_metrics:
  attempt_number: 2
  validation_status: failed
  failing_test_count: 1
  validator_error_count: 3
  changed_file_count: 1
  patch_size_bytes: 4200
  stdout_size_bytes: 1200
  stderr_size_bytes: 300
  failure_categories:
    - pytest
    - patch
  repeated_failures: true
  new_failures: false
  unrelated_file_touch: false
  syntax_regression: false
```

Metrics are stored on `OrchestratorState.attempt_metrics` and logged as
`attempt_metrics` JSONL events.

## Implemented Scoring

The evaluator compares each failed attempt with the previous attempt.

Convergence increases score when:

- validator error count decreases
- failing test count decreases
- changed file count decreases
- patch size shrinks

Divergence is detected when:

- validator/test failures increase beyond configured growth ratios
- patch size grows beyond configured ratio
- new failure signatures appear
- unrelated files are touched
- syntax regression appears
- improvement score drops below the configured continuation threshold

Stagnation is detected when the same failure signatures repeat without new
failures and without positive score.

## Config

```yaml
convergence:
  max_stagnant_attempts: 2
  max_divergent_attempts: 1
  max_patch_growth_ratio: 1.5
  max_failure_growth_ratio: 1.25
  min_improvement_score_to_continue: -1.0
  hard_stop_on_syntax_regression: true
  hard_stop_on_unrelated_file_touch: true
```

## Decisions

The evaluator emits one of:

- `continue_cheap_retry`
- `request_diagnosis`
- `pause_block_task`
- `mark_non_converging`

For now, `request_diagnosis` and hard-stop conditions create a structured
`diagnosis_needed` escalation package. No GPT/reviewer call is made yet.

Continue cheap retries while:

- retry ceiling not reached
- budget remains
- runtime remains
- divergence score below threshold
- at least one convergence signal exists

Stop cheap retries when:

- divergence threshold exceeded
- stagnation threshold exceeded
- hard retry ceiling reached
- syntax regression hard stop applies
- unrelated file hard stop applies

## Report

`report` includes the latest convergence status, action, score, reason, and
stagnant/divergent attempt counters.
