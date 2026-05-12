# Review Packet Spec

Diagnosis packets are compact and diagnosis-only.

Fields include:

- task metadata and allowed files
- attempt metrics and convergence status
- compact diff tail
- compact validation stdout/stderr tails
- explicit diagnosis question

Diagnosis responses must not include:

- direct patch payloads
- shell command execution instructions
- file write instructions
