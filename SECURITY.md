# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |
| < 0.1   | No        |

Only the latest release in the 0.1.x line receives security fixes.

---

## Reporting a vulnerability

Do not open a public GitHub issue for security reports.

Preferred: use GitHub Security Advisories for private disclosure:
https://github.com/lemnk/Sudo-agent/security/advisories/new

Include:
- Description of the issue
- Minimal proof of concept (if possible)
- Impact and attack scenario
- Affected versions or commit hash

---

## Scope

### In scope

- Approval bypass (execution when policy requires deny or approval)
- Incorrect or misleading audit records (wrong decision/outcome semantics, incorrect correlation)
- Unsafe log path handling (writing outside expected locations when given untrusted input)
- Terminal markup injection that could mislead the approver
- Sensitive data disclosure in logs or prompts
- Denial of service that affects guard reliability (e.g., excessive approval prompts, pathological inputs causing slow serialization)

### Out of scope

- Vulnerabilities in user code being guarded
- Issues in dependencies unless exploitable through SudoAgent usage
- Attacks requiring local machine compromise
- Sandboxing or process isolation (not a goal)

---

## Security model

Assumptions:
- Guarded functions are trusted code
- Inputs (args/kwargs) may be attacker-controlled
- Approver is a human in the same terminal session
- Audit log is a local JSONL file

Defenses:
- Fail-closed on policy, approval, or decision logging errors
- Terminal output escaped to prevent markup injection
- Common secret patterns redacted in logs and prompts

Non-goals:
- Preventing side effects inside the guarded function
- Protecting against a malicious local user with filesystem access

---

## Audit log limitations

- Not tamper-evident: the default `JsonlAuditLogger` uses append mode and does not provide cryptographic integrity.
- Single-process only: concurrent writes from multiple processes may interleave and produce mixed/garbled lines. Use a custom `AuditLogger` for multi-process or multi-host deployments.
