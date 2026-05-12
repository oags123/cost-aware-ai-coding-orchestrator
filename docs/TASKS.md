# Tasks

Task files define bounded work:

- `allowed_files`
- `max_attempts`
- `max_runtime_seconds`
- `max_cost_usd`
- `validation_commands`

Retry continues only while convergence policy allows. Diagnosis/escalation triggers when convergence fails or policy limits are reached.
