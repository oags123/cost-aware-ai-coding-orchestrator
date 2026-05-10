# Convergence And Divergence Logic

Status: planning only.

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

## Proposed Score

Track per attempt:

```yaml
attempt_metrics:
  failing_command_count: 2
  validator_error_count: 3
  changed_file_count: 1
  diff_line_count: 42
  syntax_passed: true
  forbidden_path_failures: 0
```

Compute:

- `convergence_score`: positive movement from previous attempt
- `divergence_score`: negative movement from previous attempt
- `stagnation_count`: repeated equivalent failures

## Escalation Rule Proposal

Continue cheap retries while:

- retry ceiling not reached
- budget remains
- runtime remains
- divergence score below threshold
- at least one convergence signal exists

Escalate when:

- divergence threshold exceeded
- stagnation threshold exceeded
- runtime exhausted
- budget exhausted
- hard retry ceiling reached
- high-risk validator failure occurs

