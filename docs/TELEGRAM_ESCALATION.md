# Telegram Escalation

Status: Step 7A blocker/stop alerts are implemented and disabled by default.
Approval modes remain future work.

Telegram is a human notification layer, not a task execution layer.

## Purpose

Notify a human when automated cheap retries and diagnosis-only escalation are no longer safe or cost-effective.

Current notifications cover blocker/stop conditions such as blocked tasks,
budget exhaustion, runtime exhaustion, no runnable tasks, system errors, and
human-attention escalation.

## Must Not Do

Telegram integration must not:

- send secrets
- send full repo dumps
- expose API keys
- approve dangerous actions automatically
- accept arbitrary shell commands
- trigger force pushes

## Proposed Message

```text
Task T-042 requires human review.
Status: escalated
Reason: divergence threshold exceeded
Budget: $0.04 remaining / $0.10 task cap
Changed files: src/parser.py, tests/test_parser.py
Validation: 1 failing pytest
Escalation package: logs/escalations/T-042-escalation.json
Suggested action: review diagnosis and approve another cheap retry or manual fix.
```

## Approval Flow

Not implemented.

Telegram may eventually support structured approvals:

- approve cheap retry
- approve expensive diagnosis
- block task
- mark manual intervention required

It should not approve expensive direct patch generation by default.

## Related Future Work

- External watchdog and heartbeat for alerts even when the orchestrator crashes.
- Robust persistent run/task state and `resume`.
- Future SafeAuto policy that alerts only on real blockers or no progress.
