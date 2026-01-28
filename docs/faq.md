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

## When should I use SQLite instead of JSONL?

- JSONL (`JSONLLedger`) is simple and inspectable, best for single-process and local/dev.
- SQLite (`SQLiteLedger`) is better for multi-process on one host (WAL mode) and for querying.

## How do I set stable identities in the ledger?

- Pass a stable `agent_id` to `SudoEngine(...)`.
- Set `policy_id` by defining a `policy_id` attribute on your policy class, or rely on the default fully qualified class name.

