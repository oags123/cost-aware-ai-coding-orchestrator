# Convergence Logic

Each attempt records deterministic metrics (validator failures, test failures, patch/stream size, file scope).

Decision actions:

- `continue_current_role_retry`
- `request_diagnosis`
- `pause_block_task`
- `mark_non_converging`

Escalation is triggered by stagnation/divergence thresholds and hard-stop rules.
