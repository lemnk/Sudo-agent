# Architecture

SudoAgent is a runtime authorization layer for tool/function calls: policy -> (optional) approval -> (optional) budgets -> record evidence -> execute -> record outcome.

## Core contract (fail-closed)

If any of these fail, the guarded function does not execute:
- policy evaluation
- approval flow (when required)
- budget check/commit (when configured)
- decision logging to the ledger and audit log

Outcome logging is best-effort and must not change the function's return value or exception.

## Components

### AsyncSudoEngine (core)

Native async orchestrator for policy evaluation, approval, budgets, and logging.

Responsibilities:
- Build a redacted `Context` from the function call (args/kwargs are redacted first).
- Evaluate `Policy.evaluate(ctx) -> PolicyResult` (deterministic, sync policy logic).
- If `REQUIRE_APPROVAL`, call `AsyncApprover.approve(ctx, result, request_id)`.
- Optionally enforce budgets (Check -> Commit).
- Write a decision record to:
  - the tamper-evident ledger (evidence)
  - the audit logger (operational record)
- Execute the function if allowed.
- Write an outcome record (best-effort).

### SudoEngine (sync compatibility wrapper)

`SudoEngine` wraps `AsyncSudoEngine` for sync code paths.

- Uses a background event loop via `run_sync`.
- Raises a clear `RuntimeError` if called from an active event loop.
- In async runtimes, use `AsyncSudoEngine` directly.

### Policy

Policies should be deterministic and side-effect-free. They return a `PolicyResult`:
- `decision`: `ALLOW`, `DENY`, or `REQUIRE_APPROVAL`
- `reason`: human-readable string
- `reason_code` (optional): stable taxonomy code

### Approver

Approvers are invoked only when policy returns `REQUIRE_APPROVAL`.

The interface supports either:
- `bool` (approved/denied), or
- a mapping that can carry `approver_id` plus a binding to `{request_id, policy_hash, decision_hash}`.

Sync and async variants exist:
- Sync: `Approver` (e.g., `InteractiveApprover`, dev-oriented)
- Async: `AsyncApprover` (recommended for services/SaaS)

For production, inject a non-interactive approver (Slack/UI/webhook/polling store).

### BudgetManager (optional)

Budgets are evaluated right before execution.

Default semantics are Check -> Commit:
- check is idempotent by `request_id` (retries do not double-charge)
- failures are fail-closed (deny)

### Ledger (evidence)

The ledger is append-only evidence, not a debug log.

By default SudoAgent writes `sudo_ledger.jsonl` using `JSONLLedger`, which:
- canonicalizes JSON and computes `entry_hash` with a `prev_entry_hash` chain
- verifies schema/ledger versions and decision/outcome linkage
- optionally signs entries with Ed25519 when a signing key is configured

For a single-host multi-process deployment, `SQLiteLedger` uses WAL mode.
If you need budgets/approvals to persist across restarts, use `SQLiteLedger` plus the durable budget/approval stores (`persistent_budget`, `SQLiteApprovalStore`).
SQLite defaults to `synchronous=FULL` for durability. If you need higher throughput and can accept reduced crash durability, set it to `NORMAL`.
Approval TTL enforcement uses wall-clock time; in production, keep NTP/time sync healthy to avoid skew.

### AuditLogger (operational)

The audit logger is an operational record (e.g., for local debugging).

By default SudoAgent writes `sudo_audit.jsonl` via `JsonlAuditLogger`. This is not tamper-evident.

## Execution flow

![SudoAgent execution flow](sudoagent_flow.png)

### Semantics table

| Path | Decision recorded | Outcome recorded | Result |
|------|-------------------|------------------|--------|
| Policy -> `ALLOW` | Yes (fail-closed) | Yes (best-effort) | Function executes |
| Policy -> `DENY` | Yes (fail-closed) | No | `raise ApprovalDenied` |
| Policy -> `REQUIRE_APPROVAL` -> approved | Yes (fail-closed) | Yes (best-effort) | Function executes |
| Policy -> `REQUIRE_APPROVAL` -> denied | Yes (fail-closed) | No | `raise ApprovalDenied` |
| Policy raises exception | Yes (`DENY`) | No | `raise PolicyError` |
| Approver raises exception | Yes (`DENY`) | No | `raise ApprovalError` |
| Decision logging fails | No | No | `raise AuditLogError` (blocks execution) |

## Security notes

- SudoAgent is not a sandbox. Side effects inside guarded functions are not prevented.
- Redaction is applied before policy evaluation, approval prompts, and ledger hashing.
- When using signing, protect private keys (secret manager / protected filesystem).

## Extending

Extension points:
- Policy: implement `evaluate(ctx) -> PolicyResult`
- Sync approver: implement `Approver.approve(ctx, result, request_id) -> bool | Mapping[str, object]`
- Async approver: implement `AsyncApprover.approve(ctx, result, request_id) -> bool | Mapping[str, object]`
- Sync ledger/logger: implement `Ledger` / `AuditLogger`
- Async ledger/logger: implement `AsyncLedger` / `AsyncAuditLogger`

Use adapters in `src/sudoagent/adapters/sync_to_async.py` when you need to bridge sync implementations into async engine wiring.

SudoAgent is intentionally small: it enforces "do not execute unless governance can be proven", and leaves orchestration to other frameworks.
