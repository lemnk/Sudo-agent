# Security Policy

## Reporting a vulnerability

Please do not open a public GitHub issue for security-sensitive reports.

Preferred: use GitHub Security Advisories for this repository (private disclosure).
Include:
- a clear description of the issue
- a minimal proof of concept (if possible)
- impact and realistic attack scenario
- affected versions / commit hash
- any suggested fix

If you are unable to use GitHub Security Advisories, open a normal issue with no details and ask for a private channel.

## In-scope

SudoAgent is a runtime guard + approval + audit logger. In scope:
- audit log integrity issues (wrong decision recorded, log tampering via path tricks)
- approval bypass (a call executes when policy requires deny/approval)
- markup/terminal injection that misleads the approver
- accidental sensitive-data disclosure in logs or terminal prompts
- denial-of-service vectors that make the guard unreliable in normal usage

## Out-of-scope

Out of scope:
- vulnerabilities inside user code being guarded
- vulnerabilities in third-party dependencies unless triggered by SudoAgent usage
- attacks requiring full local machine compromise
- sandboxing or process isolation (SudoAgent does not claim to provide isolation)

## Threat model (v0.1)

Assume:
- the guarded function is trusted code but may receive untrusted inputs
- an agent may pass attacker-controlled strings in args/kwargs
- the approver is a human in the same terminal session
- the audit log is append-only JSONL and may be read by other tools

Goals:
- fail closed: errors in policy/approval/logging should not allow execution
- minimize UI deception in the terminal approval prompt
- reduce accidental leakage of common secrets to logs by default

Non-goals:
- preventing side effects inside the guarded function
- protecting against a fully malicious local user with filesystem control
