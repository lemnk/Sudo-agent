# SudoAgent v2 Ledger Guide

This document summarizes the v2 ledger format, hashing rules, and verification workflow.

## Canonicalization and hashes
- Canonical JSON: lexicographic object keys, no extra whitespace, decimal numbers (no exponent), ISO 8601 UTC timestamps with microseconds and `Z`.
- `decision_hash`: SHA-256 over canonical JSON containing `request_id`, `decision_at`, `policy_hash`, `intent`, `resource`, `parameters`, `actor`, and `version`.
- `policy_hash`: explicit policy hash when provided; otherwise derived from policy identity plus source hash when available.
- `entry_hash`: SHA-256 over the full ledger entry with `entry_hash` set to `null`, chained via `prev_entry_hash`.
- Redaction is centralized and applied before policy evaluation, approval prompts, and hashing.

## Ledger entry fields
Each entry includes the following top-level fields:
- `schema_version`: entry schema version (e.g., `2.0`).
- `ledger_version`: ledger format version (e.g., `2.0`).
- `request_id`: UUID correlating decision and outcome.
- `created_at`: canonical UTC timestamp.
- `event`: `decision` or `outcome`.
- `action`: fully qualified function identity.
- `agent_id`: identifier for the caller/agent.
- `metadata`: safe extensible metadata (reason codes and other non-sensitive context). Redacted call inputs are stored in `parameters`.
- `entry_signature` (optional): Ed25519 signature over `entry_hash` when signing is enabled.

Decision entries include:
- `decision.policy_id`: stable policy identifier (default: fully qualified class name).
- `decision.policy_hash`: explicit policy hash when provided; otherwise derived from policy identity plus source hash when available.
- `decision.reason_code`: stable taxonomy code when provided.
- `decision.decision_hash`: binding anchor for approvals and outcomes.

Approval blocks (when present) include:
- `approval.approval_id`, `approval.state`, `approval.created_at`, `approval.resolved_at`, `approval.expires_at`
- `approval.binding`: `{request_id, policy_hash, decision_hash}`.
- `approval.approved`: boolean decision.
- `approval.approver_id`: approver identity when provided.

## Approval binding
Approval is valid only when the approver's binding matches `{request_id, policy_hash, decision_hash}`. Any mismatch fails closed and is logged as denied.

## Reason codes
SudoAgent uses stable, searchable reason codes:
- `POLICY_ALLOW_LOW_RISK`
- `POLICY_DENY_HIGH_RISK`
- `POLICY_REQUIRE_APPROVAL_HIGH_VALUE`
- `POLICY_EVALUATION_FAILED`
- `BUDGET_EXCEEDED_AGENT_RATE`
- `BUDGET_EXCEEDED_TOOL_RATE`
- `BUDGET_EVALUATION_FAILED`
- `APPROVAL_DENIED`
- `APPROVAL_PROCESS_FAILED`
- `LEDGER_WRITE_FAILED_DECISION`

## Verification
- CLI: `sudoagent verify <ledger_path>` (use `--json` for machine-readable output).
- Verification checks canonical form, schema/ledger versions, per-entry hashes, and the `prev_entry_hash` chain to detect tampering, gaps, or reordering.
- Outcome entries must reference a known decision via `decision_hash` and matching `request_id`.
- Use `sudoagent verify <ledger_path> --public-key <key.pem>` to validate signatures when present (requires `sudoagent[crypto]`).

## Key handling
- Store private keys in a secret manager or protected filesystem and never commit them.
- Rotate keys periodically and distribute public keys for verification.

## Receipt format
Receipts are JSON objects with:
- `ledger_position`
- `schema_version`
- `ledger_version`
- `request_id`
- `created_at`
- `policy_id`
- `policy_hash`
- `decision_hash`
- `entry_hash`
- `entry_signature`

## Export and search
- `sudoagent export <ledger_path> --format json|ndjson|csv`
- `sudoagent filter <ledger_path> --request-id <id> --action <action> --agent-id <agent>`
- `sudoagent search <ledger_path> --query <text> [--start <ts> --end <ts>]`
- `sudoagent receipt <ledger_path> --request-id <id>`

## Outcome logging guarantee
Outcome logging is best-effort. Failures never mask the original return value or exception from the guarded function.

## Limitations
- Single-writer only for JSONL. For multi-process deployments, use the SQLite WAL backend (`SQLiteLedger`).

## Demo workflow (deny -> approve -> verify)
```bash
python examples/v2_demo.py
sudoagent verify sudo_ledger.jsonl
sudoagent verify sudo_ledger.jsonl --json
```
The demo first denies an over-limit action, then approves it, producing chained ledger entries that verification validates.
