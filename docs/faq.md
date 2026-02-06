# FAQ

## Is SudoAgent a sandbox?

No. SudoAgent does not prevent side effects inside the guarded function, and it does not provide process isolation.

SudoAgent's job is to enforce a deterministic authorization boundary around the call (policy -> approval -> evidence -> execute).

## What is the difference between the audit log and the ledger?

By default SudoAgent writes two files:

- `sudo_audit.jsonl`: an operational record for debugging/ops. It is not tamper-evident.
- `sudo_ledger.jsonl`: append-only evidence with hash chaining. You can verify it with `sudoagent verify`.

The ledger is intended to answer: "Did we follow the process before execution?"

## What does `sudoagent verify` prove?

It verifies ledger integrity:
- entries are canonical
- schema/ledger versions match
- the hash chain is intact (detects modifications, reordering, and gaps)
- outcomes reference real decisions (by `decision_hash` + `request_id`)
- optional signatures are valid when a public key is provided

It does not prove host integrity. A compromised host can delete the ledger entirely.

## Why are some tests skipped?

Signing tests are skipped when `cryptography` is not installed.

To run them:

```bash
pip install "sudoagent[crypto]"
pytest -q
```

## Does SudoAgent support asyncio?

Yes.

- `AsyncSudoEngine` is the native async engine for services and event-loop runtimes.
- `SudoEngine` is a sync wrapper over the async core for scripts/sync apps.
- If you call `SudoEngine.execute()` from inside an active event loop, it raises a `RuntimeError`; use `AsyncSudoEngine` there.
- `SudoEngine` defaults to a JSONL ledger at `sudo_ledger.jsonl` (or pass a ledger / set `SUDOAGENT_LEDGER_PATH`).

## Can I change policy without a code deploy?

Right now policies are Python classes for determinism and testability. The roadmap includes loading signed policy bundles (e.g., Rego/OPA or signed YAML) so non-developers can promote changes without shipping new code. Until then, treat policy updates like any other code change with tests and review.

## When should I use SQLite instead of JSONL?

- JSONL (`JSONLLedger`) is simple and inspectable, best for single-process and local/dev.
- SQLite (`SQLiteLedger`) is better for multi-process on one host (WAL mode) and for querying.
- Use `persistent_budget` and `SQLiteApprovalStore` if you need budgets/approvals to survive restarts.
- SQLite defaults to `synchronous=FULL` for durability; switch to `NORMAL` if you prefer higher throughput and accept weaker crash guarantees.
- Approval TTLs rely on wall-clock time; keep NTP/time sync healthy in production.

## Is there an “enterprise” version?

The open-source engine is the core: async-native guardrail + sync wrapper + tamper-evident ledger. A future commercial control plane (“gateway”) may add multi-host ledgering, richer approvals, and SIEM/GRC integrations. There is no hidden v3 replacing OSS; the current OSS line remains supported.

## Do I need SudoAgent if I already built this?

If you already have budgets, approvals, tamper-evident logging with hash chaining, signed receipts, and verification across your services, you don’t need SudoAgent. It exists so most teams don’t have to re-implement and re-audit that stack everywhere.

## How do I set stable identities in the ledger?

- Pass a stable `agent_id` to `SudoEngine(...)`.
- Set `policy_id` by defining a `policy_id` attribute on your policy class, or rely on the default fully qualified class name.
