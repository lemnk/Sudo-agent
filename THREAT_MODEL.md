# SudoAgent Threat Model

## Scope
SudoAgent provides a runtime authorization boundary for tool/function calls and emits tamper-evident audit evidence. It is not a sandbox or isolation layer.

## Assets
- Authorization decisions (allow/deny/require_approval)
- Approval bindings and approver identity
- Ledger integrity (append-only chain)
- Redacted decision/outcome snapshots
- Persistent budget/approval state (when using SQLite-backed helpers)

## Threats mitigated
- Tampering with individual entries (hash mismatch)
- Deletion or insertion within the ledger chain (gap detection)
- Reordering of entries (prev_hash mismatch)
- Approval replay against different decisions (binding checks)
- Secret leakage via logs/prompts (deterministic redaction)
- Loss of budget/approval state across restarts when durable stores are used

## Threats not mitigated
- Host or root compromise
- Full ledger deletion by an attacker with host access
- Malicious operators with unrestricted system access
- Sandbox escapes or side effects inside guarded functions

## Assumptions
- Ledger storage is on a trusted host with standard OS protections
- When signature verification is enabled, private keys are protected
- Policies are correctly implemented and reasoned
- Durable budget/approval stores (SQLite) reside on trusted storage if enabled

## Security controls
- Fail-closed decision logging (execution blocked on decision log failure)
- Best-effort outcome logging (does not mask return values or exceptions)
- Canonical JSON + SHA-256 hash chaining
- Optional Ed25519 signatures for entry authenticity

## Deployment notes
- Default OSS deployment is local/single-host (JSONL + in-memory budgets/approvals).
- For multi-process or higher assurance, use `SQLiteLedger` plus durable budgets/approvals.
- A future gateway/control plane (commercial) may offer multi-host ledgering/approvals; it is out of scope for this OSS threat model.

## Validation matrix
- See `docs/threat_test_matrix.md` for the threat-to-test mapping and release gate commands.
