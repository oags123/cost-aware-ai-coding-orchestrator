# Escalation Policy

Status: implemented through diagnosis-needed packages and a dry-run diagnosis interface.

## Philosophy

Escalation is a cost and risk event. It should not be triggered by a single failed retry alone.

The orchestrator should escalate based on convergence collapse, divergence, risk, runtime, and budget.

## Escalation Tiers

1. Cheap retry with validator feedback.
2. Deterministic compact review packet generation.
3. Diagnosis-only reviewer interface, dry-run by default.
4. Human escalation planning.

## Expensive Model Guardrails

Default:

```yaml
allow_frontier_direct_patch: false
expensive_model_diagnosis_only: true
```

Current config:

```yaml
diagnosis:
  enabled: false
  dry_run: true
  allow_direct_patch: false
```

Expensive direct patch generation should be disabled in Phase 1.5. If added later, it must require:

- explicit human approval
- explicit budget override
- narrow allowed files
- strict patch validation
- separate audit log entry

No GPT/reviewer API call is made unless a future implementation explicitly adds
one. The current dry-run interface records structured placeholder diagnosis only.

## Escalation Triggers

Escalate to expensive diagnosis when:

- cheap retry convergence collapses
- divergence threshold is exceeded
- repeated identical failures hit stagnation threshold
- high-risk validator failures occur
- task is high risk or critical
- cheap builder requests diagnosis

Escalate to human when:

- runtime exhausted
- task budget exhausted
- project budget exhausted
- expensive call budget exhausted
- hard retry ceiling exceeded
- forbidden path or unsafe behavior repeats
