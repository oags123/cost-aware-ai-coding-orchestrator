# Safety

## Execution safety

- Model output is data, never executable shell.
- Deterministic shell wrappers enforce allowlists and timeouts.
- Patch output must be unified diff or structured JSON patch.

## Patch safety

- Validate touched files against task boundaries.
- Reject forbidden paths and out-of-workspace paths.
- Enforce max changed-file and patch-size limits.
- Run `git apply --check` before apply.

## Runtime safety

- Validators run after apply.
- Failures trigger rollback to checkpoint.
- Retries and runtime are bounded.
- Budgets and limits can block execution pre-call.
