---
id: T-001
title: Explain orchestrator package
complexity: simple
risk: low
depends_on: []
allowed_files: []
max_attempts: 1
max_runtime_seconds: 120
max_cost_usd: 0.01
escalation_allowed: true
validation_commands:
  - "python3 -m compileall coding_orchestrator"
---
Explain the package structure and verify that the orchestrator can build bounded context.
