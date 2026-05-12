# Future Provider Integration

Provider abstraction already exists in `models/provider.py`.

Future provider additions must preserve:

- no model-generated shell execution
- strict patch contract and patch safety checks
- deterministic validator and rollback behavior
- budget and limit pre-checks
- role-based routing and service-tier metadata accounting
