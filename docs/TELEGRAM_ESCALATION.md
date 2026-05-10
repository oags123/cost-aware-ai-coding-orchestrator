# Telegram Escalation Plan

Status: planning only.

Telegram is a future human notification layer, not a task execution layer.

## Purpose

Notify a human when automated cheap retries and diagnosis-only escalation are no longer safe or cost-effective.

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

Telegram may eventually support structured approvals:

- approve cheap retry
- approve expensive diagnosis
- block task
- mark manual intervention required

It should not approve expensive direct patch generation by default.

