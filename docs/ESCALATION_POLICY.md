# Escalation Policy

Escalation triggers:

- retry budget exhausted
- non-converging attempts
- high-risk/critical tasks with unresolved validator failures
- hard safety/limit blocks

Escalation output:

- structured escalation package under `logs/escalations/`
- diagnosis packet and convergence evidence
- recommended bounded next action
