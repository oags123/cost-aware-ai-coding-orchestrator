# Future Unattended SafeAuto

Status: future idea only. Not implemented.

SafeAuto, or `unattended_safe_auto`, would be an orchestrator policy for
continuing cheap automated work while deterministic safety checks remain green.
It is not a Google, OpenAI, or OpenCode feature.

## Goal

- auto-continue while tasks are safe, bounded, and converging
- pause only on real blockers
- continue other runnable tasks when one task blocks
- notify a human when intervention is needed
- add watchdog/heartbeat support later

## Boundaries

SafeAuto would not change model permissions. OpenCode permissions remain
separate from orchestrator governance.

SafeAuto would still obey:

- task file boundaries
- budget limits
- timeout limits
- retry limits
- patch validation
- convergence/divergence checks
- diagnosis-only reviewer policy
- no direct expensive-model patching

## Future Work

- queue scheduler that skips blocked tasks and continues runnable tasks
- external watchdog/heartbeat
- unattended run state summary
- explicit approval modes
- alert throttling and escalation policy
