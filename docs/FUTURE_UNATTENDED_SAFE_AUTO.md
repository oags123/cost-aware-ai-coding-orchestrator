# Future Unattended SafeAuto

Status: future idea only. Not implemented.

SafeAuto, or `unattended_safe_auto`, would be an orchestrator policy for
continuing cheap automated work while deterministic safety checks remain green.
It is not a Google, OpenAI, Gemini, or OpenCode feature.

## Goal

- auto-continue while tasks are safe, bounded, and converging
- block unsafe tasks without blocking independent runnable work
- continue other runnable tasks when one task blocks
- notify a human only on real blockers, no progress, or required attention
- keep model execution bounded by existing validators, budgets, and limits

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
- no Telegram approval mode by default

## Required Prerequisites

Do not implement SafeAuto until these are available:

1. External watchdog and heartbeat.
2. SQLite-backed run/task state.
3. Crash/restart recovery and `resume`.
4. Persistent blocked/completed/skipped task state.
5. Integration checkpoints.

## External Watchdog And Heartbeat

The watchdog must be an independent process. It should not depend on the
orchestrator remaining alive.

It should send Telegram alerts when:

- the orchestrator process dies
- the heartbeat stalls
- no task progress occurs within a configured window
- a run blocks without a final summary

## Persistent State Requirements

SafeAuto needs exact durable state before it can run unattended:

- run id and heartbeat timestamp
- task stage and final status
- dependency status
- attempt history
- blocked/completed/skipped persistence
- validation and rollback events

## Queue Behavior

SafeAuto should:

- skip blocked tasks with unmet dependencies
- continue independent tasks when one blocks
- stop only when no safe runnable tasks remain
- create a clear final run summary
- alert Telegram on real blockers or no-progress conditions

## Future Work

- queue scheduler that safely continues independent runnable tasks
- external watchdog/heartbeat process
- `resume` command backed by SQLite state
- unattended run state summary
- alert throttling and escalation policy
- explicit approval modes only after notification-only alerts are proven stable
